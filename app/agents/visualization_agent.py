"""
Visualization Agent V2 — Intent-aware chart generation with reference lines and insights.
Converts query results + analytics into Recharts-compatible chart specifications.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import VISUALIZATION_SYSTEM_PROMPT_V2


def _strip_thinking(text: str) -> str:
    """Remove <thinking>/<thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_json(text: str) -> Optional[dict]:
    """Robustly extract JSON object from LLM response."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _select_chart_type(intent: dict, data: list[dict]) -> str:
    """
    Select the most appropriate chart type based on intent and data shape.
    Intent-aware selection is more reliable than simple keyword scanning.
    """
    query_type = intent.get("query_type", "descriptive")
    entities = intent.get("entities", {})
    departments = entities.get("departments", [])

    # Trend data → line or area
    if query_type == "trend":
        return "area"

    # Comparative across departments → bar
    if query_type == "comparative" or len(departments) > 1:
        return "bar"

    # Distribution / breakdown → pie (if ≤ 8 slices)
    if query_type in ("ranking", "analytical") and len(data) <= 8:
        return "pie"

    # Ranking → bar (sorted)
    if query_type == "ranking":
        return "bar"

    # Default to bar
    return "bar"


def _build_fallback_chart(
    data: list[dict], query: str, intent: dict
) -> dict:
    """
    Generate a reasonable chart spec without LLM when the call fails.
    Uses data shape inspection and intent-aware chart type selection.
    """
    if not data:
        return {}

    keys = list(data[0].keys())
    if len(keys) < 2:
        return {}

    # Identify x-axis (first text-like field) and y-axis (first numeric field)
    x_key = keys[0]
    y_keys: list[str] = []
    for k in keys[1:]:
        try:
            float(data[0][k])
            y_keys.append(k)
        except (TypeError, ValueError):
            if not y_keys and k != x_key:
                x_key = k if not y_keys else x_key

    if not y_keys:
        y_keys = [keys[1]] if len(keys) > 1 else [keys[0]]

    chart_type = _select_chart_type(intent, data)
    primary_y = y_keys[0]

    # Build series (up to 4 metrics)
    colors = ["#6366F1", "#14B8A6", "#F59E0B", "#EF4444"]
    series = [
        {
            "dataKey": y,
            "name": y.replace("_", " ").title(),
            "color": colors[i % len(colors)],
            "type": chart_type if chart_type != "composed" else ("bar" if i == 0 else "line"),
        }
        for i, y in enumerate(y_keys[:4])
    ]

    # Reference lines for common metrics
    reference_lines = []
    for y in y_keys:
        y_lower = y.lower()
        if "attendance" in y_lower:
            reference_lines.append({
                "y": 75,
                "label": "75% Minimum",
                "color": "#EF4444",
                "strokeDasharray": "5 5",
            })
        elif "pass" in y_lower or "marks" in y_lower:
            reference_lines.append({
                "y": 40,
                "label": "40% Pass Mark",
                "color": "#F59E0B",
                "strokeDasharray": "5 5",
            })

    insight = ""
    if data:
        try:
            values = [float(row.get(primary_y) or 0) for row in data]
            avg_val = sum(values) / len(values)
            max_val = max(values)
            max_label = next(
                (str(row.get(x_key, "")) for row in data if float(row.get(primary_y) or 0) == max_val),
                ""
            )
            insight = (
                f"Average {primary_y.replace('_', ' ')}: {avg_val:.1f}%. "
                f"Highest: {max_label} at {max_val:.1f}%."
            )
        except (TypeError, ValueError):
            insight = f"Showing {len(data)} data points."

    spec = {
        "chartType": chart_type,
        "title": query[:80],
        "description": f"Showing {primary_y.replace('_', ' ')} data",
        "data": data[:100],
        "xAxis": {
            "dataKey": x_key,
            "label": x_key.replace("_", " ").title(),
        },
        "yAxis": {
            "label": primary_y.replace("_", " ").title(),
            "domain": [0, 100] if any("pct" in y or "rate" in y or "percentage" in y for y in y_keys) else ["auto", "auto"],
        },
        "series": series,
        "insight": insight,
    }

    if reference_lines:
        spec["referenceLines"] = reference_lines

    return spec


async def visualization_agent_node(state: AgentState) -> dict:
    """LangGraph node: Visualization Agent V2."""
    llm = get_llm_provider()

    data = state.get("sql_result", [])
    query = state.get("user_query", "")
    intent = state.get("intent", {})
    analytics_result = state.get("analytics_result")
    existing_insights = state.get("insights", [])

    if not data:
        return {
            "agent_used": "visualization",
            "chart_spec": None,
            "final_response": "No data available to visualize. Please query data first.",
            "error": "No data to visualize",
        }

    # Limit data rows sent to LLM (cost control)
    data_preview = data[:60]
    chart_type_hint = _select_chart_type(intent, data)

    # If analytics result is available, include its insights in the chart request
    analytics_context = ""
    if analytics_result:
        comparisons = analytics_result.get("comparisons", [])
        if comparisons:
            analytics_context = f"\n\nAnalytical context:\n{json.dumps(comparisons, indent=2, default=str)}"

    messages = [{
        "role": "user",
        "content": (
            f"User asked: '{query}'\n"
            f"Query type: {intent.get('query_type', 'descriptive')}\n"
            f"Suggested chart type: {chart_type_hint}\n"
            f"Departments: {intent.get('entities', {}).get('departments', [])}\n"
            f"Metrics: {intent.get('entities', {}).get('metrics', [])}\n"
            f"{analytics_context}\n\n"
            f"Data ({len(data)} rows, showing first {len(data_preview)}):\n"
            f"{json.dumps(data_preview, indent=2, default=str)}\n\n"
            "Generate a Recharts chart specification. Include referenceLines for attendance (75%) "
            "or marks (40%) thresholds if relevant."
        ),
    }]

    try:
        llm_response = await llm.generate(
            messages=messages,
            system_prompt=VISUALIZATION_SYSTEM_PROMPT_V2,
            temperature=0.1,
        )
        llm_response = _strip_thinking(llm_response)
        chart_spec = _extract_json(llm_response)

        if not chart_spec:
            chart_spec = _build_fallback_chart(data, query, intent)

    except Exception:
        chart_spec = _build_fallback_chart(data, query, intent)

    # Extract chart insight and merge into state insights
    chart_insight = chart_spec.get("insight", "") if chart_spec else ""
    if chart_insight and chart_insight not in existing_insights:
        existing_insights = existing_insights + [chart_insight]

    return {
        "agent_used": "visualization",
        "chart_spec": chart_spec,
        "sql_result": data,
        "insights": existing_insights,
        "final_response": chart_insight or (chart_spec.get("description", "") if chart_spec else "Chart generated."),
        "error": None,
    }
