"""
Analytics Agent — KPI calculations, comparisons, trend analysis, statistical summaries.
This agent receives raw SQL results and transforms them into analytical insights.
It behaves like a BI analyst, not a data retriever.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import ANALYTICS_AGENT_PROMPT


def _strip_thinking(text: str) -> str:
    """Remove <thinking> / <thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_json(text: str) -> Optional[dict]:
    """Robustly extract first JSON object from LLM response."""
    # Remove markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    # Find JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _compute_basic_kpis(data: list[dict]) -> dict:
    """
    Compute basic KPIs from raw SQL result data without LLM.
    Used as fallback if LLM call fails.
    """
    if not data:
        return {}

    kpis = {}
    numeric_fields = {}

    # Find numeric fields
    for key, value in data[0].items():
        try:
            float(value)
            numeric_fields[key] = []
        except (TypeError, ValueError):
            pass

    # Aggregate values
    for row in data:
        for field in numeric_fields:
            try:
                val = float(row.get(field, 0) or 0)
                numeric_fields[field].append(val)
            except (TypeError, ValueError):
                pass

    # Compute stats
    for field, values in numeric_fields.items():
        if values:
            avg = sum(values) / len(values)
            kpis[field] = {
                "value": round(avg, 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "count": len(values),
            }

    return kpis


def _is_numeric(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False

def _generate_fallback_analytics(query: str, data: list[dict], intent: dict) -> dict:
    """Generate a basic analytics result without LLM when the call fails."""
    if not data:
        return {
            "kpis": {}, "comparisons": [], "insights": ["No data available"], 
            "recommendations": [], "summary": "No data available", "alerts": []
        }

    kpis = {}
    for key, val in data[0].items():
        if isinstance(val, (int, float)) or (isinstance(val, str) and _is_numeric(val)):
            values = [float(row[key]) for row in data if row.get(key) is not None and _is_numeric(row[key])]
            if values:
                kpis[key] = {
                    "avg": round(sum(values) / len(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                    "count": len(values)
                }
    
    insights = []
    for field, stats in kpis.items():
        insights.append(f"{field}: avg={stats['avg']}, range=[{stats['min']}, {stats['max']}]")
    
    if not insights and data:
        insights.append(f"Retrieved {len(data)} records for analysis.")

    return {
        "kpis": kpis,
        "comparisons": [],
        "summary": f"Analysis of {len(data)} data points.",
        "insights": insights[:4],
        "recommendations": [],
        "alerts": [],
    }


async def analytics_agent_node(state: AgentState) -> dict:
    """
    LangGraph node: Analytics Agent.
    Transforms raw SQL results into analytical insights, KPIs, and comparisons.
    """
    llm = get_llm_provider()
    query = state.get("user_query", "")
    intent = state.get("intent", {})
    data = state.get("sql_result", [])
    existing_insights = state.get("insights", [])

    if not data:
        # No data to analyze — pass through with a note
        return {
            "agent_used": "analytics",
            "analytics_result": None,
            "insights": ["No data available for analysis. Please try a different query."],
            "recommendations": [],
            "error": None,
        }

    # Limit data for LLM context (cost control)
    data_preview = data[:80]
    entities = intent.get("entities", {})
    query_type = intent.get("query_type", "descriptive")

    analysis_prompt = (
        f"User asked: '{query}'\n"
        f"Query type: {query_type}\n"
        f"Departments: {entities.get('departments', [])}\n"
        f"Metrics of interest: {entities.get('metrics', [])}\n\n"
        f"Raw data ({len(data)} rows, showing first {len(data_preview)}):\n"
        f"{json.dumps(data_preview, indent=2, default=str)}\n\n"
        "Analyze this data and return your analytical insights as JSON."
    )

    messages = [{"role": "user", "content": analysis_prompt}]

    try:
        llm_response = await llm.generate(
            messages=messages,
            system_prompt=ANALYTICS_AGENT_PROMPT,
            temperature=0.2,
            model_name="llama-3.3-70b-versatile"
        )
        llm_response = _strip_thinking(llm_response)
        analytics_result = _extract_json(llm_response)

        if not analytics_result:
            analytics_result = _generate_fallback_analytics(query, data, intent)

    except Exception as e:
        analytics_result = _generate_fallback_analytics(query, data, intent)

    # Merge insights from analytics into state
    new_insights = analytics_result.get("insights", [])
    all_insights = list(dict.fromkeys(existing_insights + new_insights))  # deduplicate

    new_recommendations = analytics_result.get("recommendations", [])

    return {
        "agent_used": "analytics",
        "analytics_result": analytics_result,
        "insights": all_insights,
        "recommendations": new_recommendations,
        "final_response": analytics_result.get("summary", ""),
        "error": None,
    }
