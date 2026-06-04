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
from sqlalchemy import text

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
    session_key: str | None = None


async def _event_stream(
    query: str,
    history: list[dict],
    user_context: dict = None,
    session_key: str = None,
    user_id: int = None,
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
            "draft_actions": [],
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
            async for event in graph.astream_events(initial_state, version="v2"):
                kind = event["event"]
                name = event["name"]

                if kind == "on_custom_event" and name == "status_update":
                    status = event["data"].get("status")
                    if status:
                        yield f"data: {safe_json_dumps({'type': 'status', 'status': status})}\n\n"
                        
                elif kind == "on_chain_end":
                    output = event["data"].get("output")
                    if not output or not isinstance(output, dict):
                        continue

                    # If this is the classify node ending, emit the 'agent' event
                    if name == "classify":
                        agent_used = output.get("agent_used", "query")
                        pipeline = output.get("agent_pipeline", [agent_used])
                        yield f"data: {safe_json_dumps({'type': 'agent', 'agent': agent_used, 'pipeline': pipeline})}\n\n"
                        current_state.update(output)
                        
                    # If this is any other top-level agent node or the whole graph
                    elif name in ["query", "analytics", "performance", "report", "LangGraph"]:
                        current_state.update(output)

            # --- Persist to DB before closing ---
            if session_key and user_id:
                import time
                ts = int(time.time() * 1000)
                
                user_msg = {
                    "id": str(ts),
                    "role": "user", 
                    "content": query
                }
                
                assistant_msg = None
                if current_state.get("final_response"):
                    assistant_msg = {
                        "id": str(ts + 1),
                        "role": "assistant",
                        "content": current_state.get("final_response"),
                        "agent": current_state.get("agent_used", "query"),
                        "isStreaming": False
                    }
                    
                    if current_state.get("insights"):
                        assistant_msg["insights"] = current_state.get("insights")
                    if current_state.get("recommendations"):
                        assistant_msg["actions"] = current_state.get("recommendations")
                    if current_state.get("chart_spec"):
                        assistant_msg["chartSpec"] = current_state.get("chart_spec")
                        
                    sql_res = current_state.get("sql_result")
                    if sql_res and isinstance(sql_res, list) and len(sql_res) > 0:
                        assistant_msg["tableData"] = {
                            "columns": list(sql_res[0].keys()),
                            "rows": sql_res[:100],
                            "row_count": len(sql_res)
                        }
                    if current_state.get("sql_query"):
                        assistant_msg["sql"] = current_state.get("sql_query")
                    if current_state.get("report_url"):
                        assistant_msg["reportUrl"] = current_state.get("report_url")
                    if current_state.get("risk_analysis"):
                        assistant_msg["risk_analysis"] = current_state.get("risk_analysis")
                    if current_state.get("analytics_result"):
                        assistant_msg["analytics"] = current_state.get("analytics_result")
                
                r = await db.execute(text("SELECT id, messages FROM chat_sessions WHERE session_key = :sk"), {"sk": session_key})
                session_row = r.fetchone()
                
                if session_row:
                    existing_msgs = session_row.messages or []
                    existing_msgs.append(user_msg)
                    if assistant_msg:
                        existing_msgs.append(assistant_msg)
                        
                    msgs_json = safe_json_dumps(existing_msgs)
                    await db.execute(text("""
                        UPDATE chat_sessions 
                        SET messages = CAST(:msgs AS jsonb), last_agent = :agent, updated_at = NOW()
                        WHERE session_key = :sk
                    """), {
                        "msgs": msgs_json,
                        "agent": current_state.get("agent_used", "query"),
                        "sk": session_key
                    })
                else:
                    new_msgs = [user_msg]
                    if assistant_msg:
                        new_msgs.append(assistant_msg)
                        
                    msgs_json = safe_json_dumps(new_msgs)
                    title = query[:50] + "..." if len(query) > 50 else query
                    await db.execute(text("""
                        INSERT INTO chat_sessions (user_id, session_key, title, messages, last_agent)
                        VALUES (:uid, :sk, :title, CAST(:msgs AS jsonb), :agent)
                    """), {
                        "uid": user_id,
                        "sk": session_key,
                        "title": title,
                        "msgs": msgs_json,
                        "agent": current_state.get("agent_used", "query")
                    })
                await db.commit()

        # The DB session is now closed! The connection is returned to the pool.
        result = current_state

        # ── Emit: query plan ─────────────────────────────────────────────────
        query_plan = result.get("query_plan", [])
        if query_plan:
            yield f"data: {safe_json_dumps({'type': 'query_plan', 'steps': query_plan})}\n\n"
            
        # ── Emit: sql query ──────────────────────────────────────────────────
        sql_query = result.get("sql_query")
        if sql_query:
            yield f"data: {safe_json_dumps({'type': 'sql_query', 'sql': sql_query})}\n\n"

        # ── Emit: final response (streamed token by token) ───────────────────
        final_response = result.get("final_response", "")
        if final_response:
            words = final_response.split(" ")
            chunk_size = 8  # Larger chunk size for faster delivery
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i: i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield f"data: {safe_json_dumps({'type': 'token', 'content': chunk})}\n\n"
                await asyncio.sleep(0.005)  # Negligible sleep for fast fluid appearance

        # ── Emit: insights ───────────────────────────────────────────────────
        insights = result.get("insights", [])
        if insights:
            yield f"data: {safe_json_dumps({'type': 'insights', 'data': insights})}\n\n"

        # ── Emit: recommendations ────────────────────────────────────────────
        recommendations = result.get("recommendations", [])
        if recommendations:
            yield f"data: {safe_json_dumps({'type': 'recommendations', 'data': recommendations})}\n\n"

        # ── Emit: draft actions ──────────────────────────────────────────────
        draft_actions = result.get("draft_actions", [])
        if draft_actions:
            yield f"data: {safe_json_dumps({'type': 'draft_actions', 'data': draft_actions})}\n\n"

        # ── Emit: table data ─────────────────────────────────────────────────
        sql_result = result.get("sql_result", [])
        if isinstance(sql_result, list) and sql_result:
            yield f"data: {safe_json_dumps({'type': 'table', 'data': sql_result[:100]})}\n\n"

        # ── Emit: analytics result ───────────────────────────────────────────
        analytics_result = result.get("analytics_result")
        if analytics_result:
            yield f"data: {safe_json_dumps({'type': 'analytics', 'data': analytics_result})}\n\n"

        # ── Emit: chart spec ─────────────────────────────────────────────────
        chart_spec = result.get("chart_spec")
        if not chart_spec and result.get("sql_result") and result.get("intent", {}).get("needs_visualization", False):
            from app.services.visualization_service import build_chart_spec
            chart_spec = build_chart_spec(result["sql_result"], query, result["intent"])
            # Update insights if chart generated new ones
            if chart_spec and chart_spec.get("insight") and chart_spec["insight"] not in insights:
                insights.append(chart_spec["insight"])
                yield f"data: {safe_json_dumps({'type': 'insights', 'data': insights})}\n\n"
                await asyncio.sleep(0.01)

        if chart_spec:
            yield f"data: {safe_json_dumps({'type': 'chart', 'spec': chart_spec})}\n\n"

        # ── Emit: report URL ─────────────────────────────────────────────────
        report_url = result.get("report_url")
        if report_url:
            yield f"data: {safe_json_dumps({'type': 'report', 'url': report_url})}\n\n"

        # ── Emit: risk analysis ──────────────────────────────────────────────
        risk_analysis = result.get("risk_analysis")
        if risk_analysis:
            yield f"data: {safe_json_dumps({'type': 'risk', 'data': risk_analysis})}\n\n"

        # ── Emit: done ───────────────────────────────────────────────────────
        yield f"data: {safe_json_dumps({'type': 'done'})}\n\n"

    except Exception as e:
        yield f"data: {safe_json_dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield f"data: {safe_json_dumps({'type': 'done'})}\n\n"


@router.post("/stream")
async def chat_stream(
    body: ChatMessage,
    current_user: User = Depends(get_current_user),
    ai_context: dict = Depends(get_ai_context),
):
    """SSE streaming chat endpoint — V2 multi-agent supervisor with role-scoped context."""
    return StreamingResponse(
        _event_stream(
            query=body.query, 
            history=body.conversation_history, 
            user_context=ai_context,
            session_key=body.session_key,
            user_id=current_user.id
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's past chat sessions"""
    r = await db.execute(text("""
        SELECT session_key, title, last_agent, updated_at 
        FROM chat_sessions 
        WHERE user_id = :uid 
        ORDER BY updated_at DESC
        LIMIT 50
    """), {"uid": current_user.id})
    
    history = []
    for row in r.fetchall():
        history.append({
            "id": row.session_key,
            "title": row.title,
            "session_key": row.session_key,
            "last_agent": row.last_agent,
            "updated_at": row.updated_at
        })
    return {"history": history}


@router.get("/history/{session_key}")
async def get_chat_session(
    session_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get messages for a specific session"""
    r = await db.execute(text("""
        SELECT messages 
        FROM chat_sessions 
        WHERE session_key = :sk AND user_id = :uid
    """), {"sk": session_key, "uid": current_user.id})
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {"messages": row.messages}



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
