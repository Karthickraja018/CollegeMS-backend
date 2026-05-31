"""
Chat API — SSE streaming endpoint connecting to the LangGraph supervisor.
"""
import json
import asyncio
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException 
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.agents.supervisor import build_supervisor_graph
from app.agents.state import AgentState

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    query: str
    conversation_history: list[dict] = []


async def _event_stream(query: str, history: list[dict], db: AsyncSession) -> AsyncIterator[str]:
    """
    Run the LangGraph supervisor and stream SSE events.
    Event types:
      - token: streaming text chunk
      - agent: which agent was selected
      - table: tabular data for rendering
      - chart: Recharts chart spec
      - report: report download URL
      - done: stream complete
      - error: error message
    """
    try:
        graph = build_supervisor_graph(db)

        # Convert history to LangGraph message format
        lc_messages = []
        for msg in history[-10:]:  # Limit context window
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lc_messages.append((role, content))
        lc_messages.append(("user", query))

        initial_state: AgentState = {
            "messages": lc_messages,
            "user_query": query,
            "agent_used": "",
            "sql_result": [],
            "chart_spec": None,
            "report_url": None,
            "risk_analysis": None,
            "final_response": "",
            "error": None,
            "iterations": 0,
        }

        # Run graph
        result = await graph.ainvoke(initial_state)

        # Emit agent badge event
        agent_used = result.get("agent_used", "query")
        yield f"data: {json.dumps({'type': 'agent', 'agent': agent_used})}\n\n"
        await asyncio.sleep(0.01)

        # Stream the final response token by token (simulate streaming)
        final_response = result.get("final_response", "")
        if final_response:
            # Split into chunks for streaming effect
            words = final_response.split(" ")
            chunk_size = 3
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                await asyncio.sleep(0.02)

        # Emit table data if present
        if "sql_result" in result and isinstance(result["sql_result"], list):
            yield f"data: {json.dumps({'type': 'table', 'data': result['sql_result'][:100]})}\n\n"

        # Emit chart spec if present
        chart_spec = result.get("chart_spec")
        if chart_spec:
            yield f"data: {json.dumps({'type': 'chart', 'spec': chart_spec})}\n\n"

        # Emit report URL if present
        report_url = result.get("report_url")
        if report_url:
            yield f"data: {json.dumps({'type': 'report', 'url': report_url})}\n\n"

        # Emit risk analysis if present
        risk_analysis = result.get("risk_analysis")
        if risk_analysis:
            yield f"data: {json.dumps({'type': 'risk', 'data': risk_analysis})}\n\n"

        # Done event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.post("/stream")
async def chat_stream(
    body: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE streaming chat endpoint."""
    return StreamingResponse(
        _event_stream(body.query, body.conversation_history, db),
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
    Button-triggered performance analysis endpoint.
    Runs the Performance Agent on demand (not scheduled).
    Accessible to admin, principal, and HOD only.
    """
    from app.models.user import UserRole
    if current_user.role not in [UserRole.admin, UserRole.principal, UserRole.hod]:
        raise HTTPException(status_code=403, detail="Insufficient permissions for performance analysis")

    from app.agents.performance_agent import performance_agent_node
    from app.agents.state import AgentState

    initial_state: AgentState = {
        "messages": [("user", "Run full performance analysis")],
        "user_query": "Run full performance analysis",
        "agent_used": "performance",
        "sql_result": [],
        "chart_spec": None,
        "report_url": None,
        "risk_analysis": None,
        "final_response": "",
        "error": None,
        "iterations": 0,
    }

    result = await performance_agent_node(initial_state, db)
    return {
        "status": "completed",
        "risk_analysis": result.get("risk_analysis"),
        "summary": result.get("final_response"),
        "error": result.get("error"),
    }
