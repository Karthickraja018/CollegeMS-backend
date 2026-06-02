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
from sqlalchemy import text
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


async def _event_stream(
    query: str,
    history: list[dict],
    user_context: dict = None,
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

        # ── Emit: query plan ─────────────────────────────────────────────────
        query_plan = result.get("query_plan", [])
        if query_plan:
            yield f"data: {safe_json_dumps({'type': 'query_plan', 'steps': query_plan})}\n\n"

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

        # ── Emit: analysis schema ────────────────────────────────────────────
        analysis_payload = {
            "type": "analysis",
            "summary": final_response,
            "insights": result.get("insights", []),
            "table": None,
            "chart": None,
            "actions": result.get("recommendations", []),
            "report_url": result.get("report_url"),
            "analytics": result.get("analytics_result"),
            "risk_analysis": result.get("risk_analysis")
        }

        sql_result = result.get("sql_result", [])
        if isinstance(sql_result, list) and sql_result:
            analysis_payload["table"] = {
                "columns": list(sql_result[0].keys()) if sql_result else [],
                "rows": sql_result[:1000],  # Increased limit for virtualization
                "row_count": len(sql_result),
                "source": result.get("agent_used", "database")
            }

        chart_spec = result.get("chart_spec")
        if not chart_spec and sql_result and result.get("intent", {}).get("needs_visualization", False):
            from app.services.visualization_service import build_chart_spec
            chart_spec = build_chart_spec(sql_result, query, result["intent"])
            if chart_spec and chart_spec.get("insight") and chart_spec["insight"] not in analysis_payload["insights"]:
                analysis_payload["insights"].append(chart_spec["insight"])

        if chart_spec:
            analysis_payload["chart"] = chart_spec

        yield f"data: {safe_json_dumps(analysis_payload)}\n\n"

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
        _event_stream(body.query, body.conversation_history, ai_context),
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

@router.get("/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch the most recent queries successfully processed by the AI.
    """
    result = await db.execute(
        text("SELECT id, question as title, result_summary, created_at FROM query_examples ORDER BY created_at DESC LIMIT 10")
    )
    history = [dict(zip(result.keys(), row)) for row in result.fetchall()]
    return {"history": history}
