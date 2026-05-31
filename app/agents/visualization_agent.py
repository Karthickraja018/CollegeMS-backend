"""
Visualization Agent — converts tabular SQL results into Recharts-compatible JSON specs.
"""
import json
import re

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import VISUALIZATION_SYSTEM_PROMPT


def _infer_chart_type(query: str, data: list[dict]) -> str:
    """Heuristic chart type selection based on query intent."""
    q = query.lower()
    if "trend" in q or "over time" in q or "monthly" in q or "weekly" in q:
        return "area"
    if "compare" in q or "comparison" in q or "vs" in q:
        return "bar"
    if "distribution" in q or "breakdown" in q or "percentage" in q:
        return "pie"
    if len(data) > 0 and isinstance(list(data[0].values())[0], (int, float)):
        return "bar"
    return "bar"


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response."""
    # Try to find JSON block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError("Could not extract valid JSON from visualization response.")


async def visualization_agent_node(state: AgentState) -> dict:
    """LangGraph node: Visualization Agent."""
    llm = get_llm_provider()

    data = state.get("sql_result", [])
    query = state.get("user_query", "")

    if not data:
        return {
            "agent_used": "visualization",
            "chart_spec": None,
            "final_response": "No data available to visualize. Please try querying data first.",
            "error": "No data to visualize",
        }

    # Limit data rows sent to LLM (cost control)
    data_preview = data[:50]

    messages = [
        {
            "role": "user",
            "content": (
                f"User wants to visualize: '{query}'\n\n"
                f"Available data ({len(data)} rows, showing first {len(data_preview)}):\n"
                f"{json.dumps(data_preview, indent=2, default=str)}\n\n"
                "Generate a Recharts chart specification."
            ),
        }
    ]

    try:
        llm_response = await llm.generate(
            messages=messages,
            system_prompt=VISUALIZATION_SYSTEM_PROMPT,
            temperature=0.1,
        )
        chart_spec = _extract_json(llm_response)
    except Exception as e:
        # Fallback: generate a basic bar chart spec without LLM
        if data:
            keys = list(data[0].keys())
            x_key = keys[0] if keys else "label"
            y_key = keys[1] if len(keys) > 1 else keys[0]
            chart_spec = {
                "chartType": "bar",
                "title": f"Chart: {query[:60]}",
                "description": "Auto-generated chart",
                "data": data_preview,
                "xAxis": {"dataKey": x_key, "label": x_key.replace("_", " ").title()},
                "yAxis": {"label": y_key.replace("_", " ").title()},
                "series": [{"dataKey": y_key, "name": y_key.replace("_", " ").title(), "color": "#6366F1"}],
                "insight": f"Showing {len(data)} records.",
            }
        else:
            chart_spec = None

    return {
        "agent_used": "visualization",
        "chart_spec": chart_spec,
        "sql_result": data,
        "final_response": chart_spec.get("insight", "Chart generated.") if chart_spec else "Could not generate chart.",
        "error": None,
    }
