"""
Visualization Agent — Generates Recharts JSON specs from SQL results.
"""
import json
import re
import time
from typing import Optional

from langchain_core.callbacks.manager import adispatch_custom_event
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import VISUALIZATION_SYSTEM_PROMPT_V2

def _strip_thinking(text: str) -> str:
    """Remove <thinking> blocks."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()

def _extract_chart_spec(text: str) -> Optional[dict]:
    """Extract JSON object from LLM response."""
    text = _strip_thinking(text)
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

async def visualization_agent_node(state: AgentState) -> dict:
    """
    LangGraph node: Generates chart specification from data.
    Runs concurrently with analytics_agent.
    """
    await adispatch_custom_event("status_update", {"status": "Generating Visualization"})
    start_time = time.time()
    
    llm = get_llm_provider()
    timing_metrics = state.get("timing_metrics", {})
    intent = state.get("intent", {})
    sql_result = state.get("sql_result", [])
    
    if not sql_result:
        timing_metrics["visualization_time"] = round(time.time() - start_time, 2)
        return {"timing_metrics": timing_metrics}
        
    query_type = intent.get("query_type", "descriptive")
    
    # Cap data preview to avoid context overflow
    data_preview = sql_result[:60]
    
    visualization_request = (
        f"Generate a chart configuration based on this data.\n\n"
        f"Query type: {query_type}\n"
        f"Data ({len(sql_result)} rows, showing {len(data_preview)}):\n"
        f"{json.dumps(data_preview, default=str)}"
    )
    
    messages = [{"role": "user", "content": visualization_request}]
    
    try:
        response = await llm.generate(
            messages=messages,
            system_prompt=VISUALIZATION_SYSTEM_PROMPT_V2,
            temperature=0.1,
            model_name="llama-3.1-8b-instant"
        )
        
        chart_spec = _extract_chart_spec(response)
        timing_metrics["visualization_time"] = round(time.time() - start_time, 2)
        
        if chart_spec:
            return {
                "chart_spec": chart_spec,
                "timing_metrics": timing_metrics
            }
            
    except Exception as e:
        print(f"Visualization agent failed: {e}")
        
    timing_metrics["visualization_time"] = round(time.time() - start_time, 2)
    return {"timing_metrics": timing_metrics}
