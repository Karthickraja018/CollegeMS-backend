"""
Visualization Agent — Generates Recharts JSON specs from SQL results.

V2 Improvements:
  1. Upgraded model: llama-3.3-70b-versatile (was llama-3.1-8b-instant)
  2. Column-name injection: actual data keys sent to prompt (fixes dataKey mismatch)
  3. Rule-based fallback: _generate_fallback_chart_spec() — no more silent failures
  4. Analytics context: analytics_result summary fed into prompt
  5. Data-shape heuristics: _inspect_data_shape() injects chart-type hints
  6. Post-generation validation: repairs invalid dataKey references automatically
  7. Reference lines: auto-added for percentage data (75% attendance, 40% pass threshold)
"""
import json
import re
import time
from typing import Optional

from langchain_core.callbacks.manager import adispatch_custom_event

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import VISUALIZATION_SYSTEM_PROMPT_V2


# ── Helpers ─────────────────────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Remove <thinking> / <thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_chart_spec(text: str) -> Optional[dict]:
    """Extract first valid JSON object from LLM response."""
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


def _inspect_data_shape(data: list[dict]) -> dict:
    """
    Inspect data shape and return heuristic hints for chart selection.

    Returns a dict with:
      - columns: all column names
      - numeric_cols: columns whose values are numeric
      - string_cols: columns whose values are strings / labels
      - has_time_col: whether a time/date dimension is present
      - has_percentage_values: whether any numeric column looks like a %
      - row_count: number of data rows
      - suggested_chart_type: "bar" | "line" | "area" | "pie" | "composed"
      - suggested_x_key: the best x-axis candidate
      - suggested_series_keys: list of numeric columns suitable for series
    """
    if not data:
        return {}

    columns = list(data[0].keys())
    numeric_cols: list[str] = []
    string_cols: list[str] = []

    TIME_KEYWORDS = {"date", "month", "year", "week", "quarter", "semester", "period", "time"}
    PCT_KEYWORDS = {"pct", "percent", "rate", "percentage", "ratio", "score"}

    for key in columns:
        sample_vals = [row.get(key) for row in data[:10] if row.get(key) is not None]
        if sample_vals:
            try:
                [float(v) for v in sample_vals]
                numeric_cols.append(key)
            except (TypeError, ValueError):
                string_cols.append(key)
        else:
            string_cols.append(key)

    has_time_col = any(
        any(kw in col.lower() for kw in TIME_KEYWORDS) for col in columns
    )
    has_percentage_values = any(
        any(kw in col.lower() for kw in PCT_KEYWORDS) for col in numeric_cols
    )

    # Best x-axis candidate: prefer time columns, then first string col
    suggested_x_key = string_cols[0] if string_cols else (numeric_cols[0] if numeric_cols else columns[0])
    for col in columns:
        if any(kw in col.lower() for kw in TIME_KEYWORDS):
            suggested_x_key = col
            break

    suggested_series_keys = [c for c in numeric_cols if c != suggested_x_key]

    # Heuristic chart type
    if has_time_col:
        suggested_chart_type = "line"
    elif len(data) <= 6 and len(numeric_cols) == 1:
        # Small dataset, single metric → simple bar
        suggested_chart_type = "bar"
    elif len(numeric_cols) >= 3:
        # Many metrics → composed (bar + line)
        suggested_chart_type = "composed"
    elif len(data) >= 2 and len(string_cols) >= 1 and len(numeric_cols) >= 1:
        suggested_chart_type = "bar"
    else:
        suggested_chart_type = "bar"

    return {
        "columns": columns,
        "numeric_cols": numeric_cols,
        "string_cols": string_cols,
        "has_time_col": has_time_col,
        "has_percentage_values": has_percentage_values,
        "row_count": len(data),
        "suggested_chart_type": suggested_chart_type,
        "suggested_x_key": suggested_x_key,
        "suggested_series_keys": suggested_series_keys,
    }


def _generate_fallback_chart_spec(
    data: list[dict], user_query: str, hints: dict
) -> dict:
    """
    Rule-based fallback chart spec when the LLM fails or returns invalid JSON.
    Deterministically builds a valid Recharts-compatible spec from data shape.
    Returns empty dict only when data is empty.
    """
    if not data or not hints.get("columns"):
        return {}

    COLORS = [
        "#6366F1", "#14B8A6", "#F59E0B",
        "#EF4444", "#8B5CF6", "#10B981",
        "#F97316", "#06B6D4",
    ]

    chart_type = hints.get("suggested_chart_type", "bar")
    x_key = hints.get("suggested_x_key", hints.get("columns", ["name"])[0])
    series_keys = hints.get("suggested_series_keys", [])
    has_pct = hints.get("has_percentage_values", False)

    # Limit display data
    display_data = data[:25]

    series = [
        {
            "dataKey": key,
            "name": key.replace("_", " ").title(),
            "color": COLORS[i % len(COLORS)],
            "type": "bar" if chart_type in ("bar", "composed") and i == 0 else
                    "line" if chart_type in ("line", "composed") else chart_type,
        }
        for i, key in enumerate(series_keys[:4])  # Max 4 series
    ]

    # If we couldn't build any series, use the first numeric column we can find
    if not series and hints.get("numeric_cols"):
        fallback_key = hints["numeric_cols"][0]
        series = [{
            "dataKey": fallback_key,
            "name": fallback_key.replace("_", " ").title(),
            "color": COLORS[0],
            "type": "bar",
        }]

    spec: dict = {
        "chartType": chart_type,
        "title": f"Data Overview — {user_query[:70]}",
        "description": (
            f"Showing {len(data)} records across "
            f"{len(series_keys)} metric(s)."
        ),
        "data": display_data,
        "xAxis": {
            "dataKey": x_key,
            "label": x_key.replace("_", " ").title(),
        },
        "yAxis": {
            "label": series[0]["name"] if series else "Value",
            **({"domain": [0, 100]} if has_pct else {}),
        },
        "series": series,
        "insight": (
            f"Review the {len(data)} data points for patterns. "
            f"{'Values above 75% meet the attendance threshold.' if has_pct else ''}"
        ).strip(),
    }

    # Auto reference lines for percentage data
    if has_pct:
        spec["referenceLines"] = [
            {
                "y": 75,
                "label": "75% Attendance Min",
                "color": "#EF4444",
                "strokeDasharray": "5 5",
            },
            {
                "y": 40,
                "label": "40% Pass Mark",
                "color": "#F59E0B",
                "strokeDasharray": "3 3",
            },
        ]

    return spec


def _repair_chart_spec(chart_spec: dict, hints: dict) -> tuple[dict, bool]:
    """
    Validate and auto-repair dataKey references in a chart spec.
    Returns (repaired_spec, was_repaired).
    """
    valid_keys = set(hints.get("columns", []))
    if not valid_keys:
        return chart_spec, False

    repaired = False

    # Repair xAxis dataKey
    x_axis = chart_spec.get("xAxis", {})
    if isinstance(x_axis, dict) and x_axis.get("dataKey") not in valid_keys:
        x_axis["dataKey"] = hints.get("suggested_x_key", list(valid_keys)[0])
        chart_spec["xAxis"] = x_axis
        repaired = True

    # Repair series dataKeys
    numeric_cols = hints.get("numeric_cols", [])
    for i, s in enumerate(chart_spec.get("series", [])):
        if s.get("dataKey") not in valid_keys:
            # Assign the i-th available numeric column
            if i < len(numeric_cols):
                s["dataKey"] = numeric_cols[i]
            elif numeric_cols:
                s["dataKey"] = numeric_cols[0]
            repaired = True

    return chart_spec, repaired


# ── Main Node ────────────────────────────────────────────────────────────────

async def visualization_agent_node(state: AgentState) -> dict:
    """
    LangGraph node: Generates chart specification from data.

    Runs AFTER analytics_agent (sequential) so it can incorporate
    analytics_result insights into the chart prompt.
    """
    await adispatch_custom_event("status_update", {"status": "Generating Visualization"})
    start_time = time.time()

    llm = get_llm_provider()
    timing_metrics = state.get("timing_metrics", {})
    intent = state.get("intent", {})
    sql_result = state.get("sql_result", [])
    user_query = state.get("user_query", "")
    analytics_result = state.get("analytics_result", None)

    if not sql_result:
        timing_metrics["visualization_time"] = round(time.time() - start_time, 2)
        return {"timing_metrics": timing_metrics}

    query_type = intent.get("query_type", "descriptive")

    # ── Step 1: Inspect data shape for heuristic hints ───────────────────────
    hints = _inspect_data_shape(sql_result)
    data_preview = sql_result[:60]

    # ── Step 2: Build analytics context summary ───────────────────────────────
    analytics_summary = ""
    if analytics_result:
        summary = analytics_result.get("summary", "")
        comparisons = analytics_result.get("comparisons", [])
        kpis = analytics_result.get("kpis", {})
        insights = analytics_result.get("insights", [])

        parts = []
        if summary:
            parts.append(f"Analytics Summary: {summary}")
        if comparisons:
            parts.append(f"Key Comparisons: {json.dumps(comparisons[:3], default=str)}")
        if kpis:
            parts.append(f"Key KPIs: {json.dumps(kpis, default=str)}")
        if insights:
            parts.append(f"Key Insights: {insights[:2]}")
        if parts:
            analytics_summary = "\n".join(parts)

    # ── Step 3: Build enriched visualization request ─────────────────────────
    visualization_request = (
        f'User\'s original question: "{user_query}"\n'
        f"Query type: {query_type}\n"
        f"Total rows returned: {len(sql_result)} (showing first {len(data_preview)})\n\n"
        f"━━ COLUMN NAMES — use EXACTLY these strings for all dataKey fields ━━\n"
        f"All columns:     {json.dumps(hints.get('columns', []))}\n"
        f"Numeric columns: {json.dumps(hints.get('numeric_cols', []))}\n"
        f"Label columns:   {json.dumps(hints.get('string_cols', []))}\n"
        f"Best x-axis key: \"{hints.get('suggested_x_key', '')}\"\n"
        f"Has time dimension: {hints.get('has_time_col', False)}\n"
        f"Has percentage values: {hints.get('has_percentage_values', False)}\n"
        f"Heuristic chart suggestion: {hints.get('suggested_chart_type', 'bar')}\n"
    )

    if analytics_summary:
        visualization_request += f"\n━━ ANALYTICS CONTEXT (use this for the insight field) ━━\n{analytics_summary}\n"

    visualization_request += (
        f"\nData (first {len(data_preview)} rows):\n"
        f"{json.dumps(data_preview, default=str)}\n\n"
        f"REMINDER: Every dataKey value you write MUST appear in the column list above. "
        f"Do NOT invent new field names."
    )

    messages = [{"role": "user", "content": visualization_request}]

    # ── Step 4: Call LLM (upgraded model) ────────────────────────────────────
    try:
        response = await llm.generate(
            messages=messages,
            system_prompt=VISUALIZATION_SYSTEM_PROMPT_V2,
            temperature=0.1,
            model_name="llama-3.3-70b-versatile",  # Upgraded from llama-3.1-8b-instant
        )

        chart_spec = _extract_chart_spec(response)

        if chart_spec:
            # ── Step 5: Validate & repair dataKey references ─────────────────
            chart_spec, was_repaired = _repair_chart_spec(chart_spec, hints)
            if was_repaired:
                print("[VisualizationAgent] Auto-repaired invalid dataKey references.")

            timing_metrics["visualization_time"] = round(time.time() - start_time, 2)
            return {
                "chart_spec": chart_spec,
                "timing_metrics": timing_metrics,
            }

        print("[VisualizationAgent] LLM returned no parseable JSON — using fallback.")

    except Exception as e:
        print(f"[VisualizationAgent] LLM call failed: {e} — using fallback.")

    # ── Step 6: Rule-based fallback — never returns empty ────────────────────
    fallback_spec = _generate_fallback_chart_spec(sql_result, user_query, hints)
    timing_metrics["visualization_time"] = round(time.time() - start_time, 2)

    if fallback_spec:
        return {
            "chart_spec": fallback_spec,
            "timing_metrics": timing_metrics,
        }

    return {"timing_metrics": timing_metrics}
