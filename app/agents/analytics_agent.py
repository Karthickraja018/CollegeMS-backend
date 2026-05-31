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


def _generate_fallback_analytics(
    query: str, data: list[dict], intent: dict
) -> dict:
    """Generate a basic analytics result without LLM when the call fails."""
    departments = intent.get("entities", {}).get("departments", [])
    metrics = intent.get("entities", {}).get("metrics", [])
    query_type = intent.get("query_type", "descriptive")

    kpis = _compute_basic_kpis(data)

    comparisons = []
    if query_type == "comparative" and len(departments) >= 2:
        # Try to extract department comparison from data
        dept_data: dict[str, dict] = {}
        for row in data:
            dept_name = (
                row.get("department")
                or row.get("dept")
                or row.get("department_name")
                or ""
            )
            if dept_name:
                dept_data[dept_name] = row

        dept_names = list(dept_data.keys())
        if len(dept_names) >= 2:
            for metric in metrics or list(kpis.keys())[:1]:
                field = metric.replace("_pct", "_pct").replace("_", "_")
                # Try several field name variants
                for variant in [field, metric, metric.replace("_pct", ""), "avg_" + field]:
                    vals = {d: dept_data[d].get(variant) for d in dept_names if dept_data[d].get(variant) is not None}
                    if len(vals) >= 2:
                        d_list = list(vals.items())
                        a_name, a_val = d_list[0]
                        b_name, b_val = d_list[1]
                        try:
                            comparisons.append({
                                "group_a": a_name,
                                "group_b": b_name,
                                "metric": metric,
                                "a_value": round(float(a_val), 2),
                                "b_value": round(float(b_val), 2),
                                "difference": round(abs(float(a_val) - float(b_val)), 2),
                                "winner": a_name if float(a_val) > float(b_val) else b_name,
                            })
                        except (TypeError, ValueError):
                            pass
                        break

    insights = []
    if comparisons:
        comp = comparisons[0]
        insights.append(
            f"{comp['winner']} has higher {comp['metric'].replace('_', ' ')} "
            f"({comp['a_value'] if comp['winner'] == comp['group_a'] else comp['b_value']:.1f}%) "
            f"compared to the other department ({comp['difference']:.1f}% difference)."
        )

    if not insights and data:
        insights.append(f"Retrieved {len(data)} records for analysis.")

    return {
        "kpis": kpis,
        "comparisons": comparisons,
        "summary": f"Analysis of {len(data)} data points.",
        "insights": insights,
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
