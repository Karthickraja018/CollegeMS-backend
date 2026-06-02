"""
Chat API V2 — SSE streaming endpoint connecting to the V2 LangGraph supervisor.

Event types emitted:
  - agent       : which agent(s) are being used
  - query_plan  : numbered plan steps from Query Agent
  - token       : streaming text chunk
  - insights    : bullet insight list
  - recommendations : actionable recommendations
  - table       : tabular data for rendering
  - chart       : Recharts chart spec
  - report      : report download URL
  - risk        : risk analysis data from Performance Agent
  - analytics   : analytics result (KPIs, comparisons)
  - done        : stream complete
  - error       : error message
"""
import json
import asyncio
from typing import AsyncIterator
import decimal
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, get_ai_context
from app.models.user import User
from app.agents.supervisor import build_supervisor_graph
from app.agents.state import AgentState


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def safe_json_dumps(obj) -> str:
    return json.dumps(obj, cls=CustomJSONEncoder)


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    query: str
    conversation_history: list[dict] = []
    session_key: str = None


async def _event_stream(
    query: str,
    history: list[dict],
    user_context: dict = None,
    session_key: str = None,
    current_user: User = None,
) -> AsyncIterator[str]:
    """
    Run the V2 LangGraph supervisor and stream SSE events.
    The database connection is closed immediately after the graph runs to free up pool resources.
    """
    try:
        from app.database import AsyncSessionLocal
        
        # Convert conversation history to LangGraph message format
        lc_messages = []
        for msg in history[-10:]:  # Limit context window to last 10 turns
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lc_messages.append((role, content))
        lc_messages.append(("user", query))

        # Role context injected so LLM can respect data access boundaries
        user_context = user_context or {}

        initial_state: AgentState = {
            "messages": lc_messages,
            "user_query": query,
            "memory_context": {},
            "intent": {},
            "query_plan": [],
            "agent_used": "",
            "agent_pipeline": [],
            "sql_result": [],
            "analytics_result": None,
            "chart_spec": None,
            "report_url": None,
            "risk_analysis": None,
            "final_response": "",
            "insights": [],
            "recommendations": [],
            "error": None,
            "iterations": 0,
            # Role-scoped context — passed to agents to enforce data access
            "user_role": user_context.get("user_role", "faculty"),
            "user_department_id": user_context.get("department_id"),
            "is_institution_wide": user_context.get("is_institution_wide", False),
            "student_filter": user_context.get("student_filter", "assigned"),
            "dept_filter_sql": user_context.get("department_filter_sql", ""),
            "student_filter_sql": user_context.get("student_filter_sql", ""),
        }

        current_state = initial_state

        # Run the entire Graph within the DB session context
        async with AsyncSessionLocal() as db:
            graph = build_supervisor_graph(db)
            async for output in graph.astream(initial_state):
                for node_name, state in output.items():
                    current_state = state
                    if node_name == "classify":
                        agent_used = state.get("agent_used", "query")
                        pipeline = state.get("agent_pipeline", [agent_used])
                        yield f"data: {safe_json_dumps({'type': 'agent', 'agent': agent_used, 'pipeline': pipeline})}\n\n"

        # The DB session is now closed! The connection is returned to the pool.
        result = current_state

        # Emit a single structured 'analysis' event instead of chunks
        insights = result.get("insights", [])
        sql_result = result.get("sql_result", [])
        
        chart_spec = result.get("chart_spec")
        if not chart_spec and sql_result and result.get("intent", {}).get("needs_visualization", False):
            from app.services.visualization_service import build_chart_spec
            chart_spec = build_chart_spec(sql_result, query, result.get("intent", {}))
            if chart_spec and chart_spec.get("insight") and chart_spec["insight"] not in insights:
                insights.append(chart_spec["insight"])

        analysis_payload = {
            "type": "analysis",
            "summary": result.get("final_response", ""),
            "insights": insights,
            "table": sql_result[:100] if sql_result else None,
            "chart": chart_spec,
            "actions": result.get("recommendations", []),
            "report_url": result.get("report_url"),
            "analytics": result.get("analytics_result"),
            "risk_analysis": result.get("risk_analysis")
        }
        
        yield f"data: {safe_json_dumps(analysis_payload)}\n\n"
        yield f"data: {safe_json_dumps({'type': 'done'})}\n\n"

        # Save to database
        if current_user:
            import uuid
            from sqlalchemy import text
            s_key = session_key or str(uuid.uuid4())
            title = query[:50] + "..." if len(query) > 50 else query
            agent_used = result.get("agent_used", "query")
            
            # Combine history and current message
            import copy
            saved_messages = copy.deepcopy(history)
            saved_messages.append({"role": "user", "content": query})
            
            # Save assistant response
            assistant_msg = {
                "role": "assistant",
                "content": analysis_payload["summary"],
                "agent": agent_used,
                "tableData": {"rows": analysis_payload["table"]} if analysis_payload["table"] else None,
                "chartSpec": analysis_payload["chart"],
                "insights": analysis_payload["insights"],
                "actions": analysis_payload["actions"]
            }
            saved_messages.append(assistant_msg)
            
            async with AsyncSessionLocal() as db_session:
                # Check if session exists
                check_q = text("SELECT id FROM chat_sessions WHERE session_key = :sk")
                res = await db_session.execute(check_q, {"sk": s_key})
                existing = res.scalar()
                
                if existing:
                    upd_q = text("""
                        UPDATE chat_sessions 
                        SET messages = :msgs, last_agent = :agent, updated_at = NOW() 
                        WHERE session_key = :sk
                    """)
                    await db_session.execute(upd_q, {
                        "msgs": safe_json_dumps(saved_messages), 
                        "agent": agent_used, 
                        "sk": s_key
                    })
                else:
                    ins_q = text("""
                        INSERT INTO chat_sessions (user_id, session_key, title, messages, last_agent)
                        VALUES (:uid, :sk, :title, :msgs, :agent)
                    """)
                    await db_session.execute(ins_q, {
                        "uid": current_user.id,
                        "sk": s_key,
                        "title": title,
                        "msgs": safe_json_dumps(saved_messages),
                        "agent": agent_used
                    })
                await db_session.commit()

    except Exception as e:
        yield f"data: {safe_json_dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield f"data: {safe_json_dumps({'type': 'done'})}\n\n"



@router.get("/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text
    query = text("""
        SELECT id, session_key, title, last_agent, updated_at
        FROM chat_sessions
        WHERE user_id = :uid
        ORDER BY updated_at DESC
        LIMIT 50
    """)
    result = await db.execute(query, {"uid": current_user.id})
    rows = result.fetchall()
    
    sessions = []
    for row in rows:
        sessions.append({
            "id": row.id,
            "session_key": row.session_key,
            "title": row.title or "New Chat",
            "result_summary": row.title or "Chat Session",
            "last_agent": row.last_agent,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return {"history": sessions}


@router.get("/history/{session_key}")
async def get_chat_session(
    session_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text
    query = text("""
        SELECT messages, title
        FROM chat_sessions
        WHERE user_id = :uid AND session_key = :sk
    """)
    result = await db.execute(query, {"uid": current_user.id, "sk": session_key})
    row = result.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Chat session not found")
        
    return {
        "session_key": session_key,
        "title": row.title,
        "messages": row.messages if row.messages else []
    }


@router.post("/stream")
async def chat_stream(
    body: ChatMessage,
    current_user: User = Depends(get_current_user),
    ai_context: dict = Depends(get_ai_context),
):
    """SSE streaming chat endpoint — V2 multi-agent supervisor with role-scoped context."""
    return StreamingResponse(
        _event_stream(body.query, body.conversation_history, ai_context, body.session_key, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/analyze-performance")
async def trigger_performance_analysis(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Button-triggered full performance analysis.
    Runs the Performance Agent V2 on demand.
    Accessible to admin, principal, and HOD only.
    """
    from app.models.user import UserRole
    if current_user.role not in [UserRole.admin, UserRole.principal, UserRole.hod]:
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions for performance analysis",
        )

    from app.agents.performance_agent import performance_agent_node

    # Build a minimal state for performance analysis
    perf_state: AgentState = {
        "messages": [("user", "Run full performance analysis for all departments")],
        "user_query": "Run full performance analysis for all departments",
        "memory_context": {},
        "intent": {
            "query_type": "predictive",
            "entities": {"departments": [], "metrics": ["risk_score"], "time": None},
            "needs_performance": True,
            "agent_pipeline": ["performance"],
            "enriched_query": "Run full performance analysis for all departments",
        },
        "query_plan": [],
        "agent_used": "performance",
        "agent_pipeline": ["performance"],
        "sql_result": [],
        "analytics_result": None,
        "chart_spec": None,
        "report_url": None,
        "risk_analysis": None,
        "final_response": "",
        "insights": [],
        "recommendations": [],
        "error": None,
        "iterations": 0,
    }

    result = await performance_agent_node(perf_state, db)

    return {
        "status": "completed",
        "risk_analysis": result.get("risk_analysis"),
        "insights": result.get("insights", []),
        "recommendations": result.get("recommendations", []),
        "summary": result.get("final_response"),
        "error": result.get("error"),
    }
