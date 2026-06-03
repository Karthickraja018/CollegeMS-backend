"""
Visualization Service
Converts query results + analytics into Recharts-compatible chart specifications deterministically.
"""

def select_chart_type(intent: dict, data: list[dict]) -> str:
    query_type = intent.get("query_type", "descriptive")
    entities = intent.get("entities", {})
    departments = entities.get("departments", [])

    x_key = list(data[0].keys())[0] if data else ""
    x_key_lower = x_key.lower()
    is_time_series = any(word in x_key_lower for word in ["date", "month", "year", "day", "time"])

    if query_type == "trend" or is_time_series:
        return "line"
    if query_type == "comparative" or len(departments) > 1:
        return "bar"
    if query_type in ("ranking", "analytical") and len(data) <= 8:
        return "pie"
    if query_type == "ranking":
        return "bar"
    return "bar"

def build_chart_spec(data: list[dict], query: str, intent: dict) -> dict:
    if not data:
        return {}

    keys = list(data[0].keys())
    if len(keys) < 2:
        return {}

    x_key = keys[0]
    y_keys: list[str] = []
    
    ignore_as_y = {"year", "month", "day", "id", "student_id", "subject_id", "department_id"}
    
    for k in keys[1:]:
        if k.lower() in ignore_as_y or k.lower().endswith("_id"):
            continue
        try:
            float(data[0][k] if data[0][k] is not None else 0)
            y_keys.append(k)
        except (TypeError, ValueError):
            if not y_keys and k != x_key:
                x_key = k if not y_keys else x_key

    if not y_keys:
        y_keys = [keys[1]] if len(keys) > 1 else [keys[0]]

    chart_type = select_chart_type(intent, data)
    primary_y = y_keys[0]

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
            avg_val = sum(values) / len(values) if values else 0
            max_val = max(values) if values else 0
            max_label = next(
                (str(row.get(x_key, "")) for row in data if float(row.get(primary_y) or 0) == max_val),
                ""
            )
            insight = (
                f"Average {primary_y.replace('_', ' ')}: {avg_val:.1f}. "
                f"Highest: {max_label} at {max_val:.1f}."
            )
        except (TypeError, ValueError):
            insight = f"Showing {len(data)} data points."

    month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    if x_key.lower() == "month":
        for row in data:
            try:
                m = int(float(row[x_key]))
                if 1 <= m <= 12:
                    row[x_key] = month_names[m]
            except (TypeError, ValueError):
                pass

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
