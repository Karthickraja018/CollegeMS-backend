"""
Report Agent V2 — Dynamic data collection with AI-driven section generation.
Produces formal institutional reports with insights, department analysis, and recommendations.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import REPORT_SYSTEM_PROMPT_V2
from app.config import get_settings


def _strip_thinking(text_content: str) -> str:
    """Remove <thinking>/<thought> blocks from model output."""
    text_content = re.sub(r"<thinking>.*?</thinking>", "", text_content, flags=re.DOTALL | re.IGNORECASE)
    text_content = re.sub(r"<thought>.*?</thought>", "", text_content, flags=re.DOTALL | re.IGNORECASE)
    return text_content.strip()


# ── Dynamic Query Templates ────────────────────────────────────────────────────

async def _query_department_summary(db: AsyncSession, dept_name: Optional[str] = None) -> list[dict]:
    """Gather department-level performance summary."""
    dept_filter = ""
    if dept_name:
        dept_filter = f"AND LOWER(d.name) = LOWER('{dept_name.replace(chr(39), chr(39)+chr(39))}')"

    sql = text(f"""
        SELECT
            d.name              AS department,
            d.code              AS dept_code,
            COUNT(DISTINCT s.id) AS total_students,
            ROUND(
                AVG(CASE WHEN a.status = 'present' THEN 100.0 ELSE 0 END)::numeric, 2
            ) AS avg_attendance_pct,
            ROUND(
                AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2
            ) AS avg_marks_pct,
            COUNT(CASE WHEN s.risk_score >= 61 THEN 1 END) AS high_risk_students,
            COUNT(CASE WHEN s.risk_score >= 81 THEN 1 END) AS critical_students
        FROM departments d
        LEFT JOIN students s ON s.department_id = d.id
        LEFT JOIN attendance a ON a.student_id = s.id
        LEFT JOIN marks m ON m.student_id = s.id
        WHERE 1=1 {dept_filter}
        GROUP BY d.name, d.code
        ORDER BY d.name
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


async def _query_subject_pass_rates(db: AsyncSession, dept_name: Optional[str] = None) -> list[dict]:
    """Gather subject-level pass rates (bottom 20 for report)."""
    dept_filter = ""
    if dept_name:
        dept_filter = f"AND LOWER(d.name) = LOWER('{dept_name.replace(chr(39), chr(39)+chr(39))}')"

    sql = text(f"""
        SELECT
            sub.name            AS subject,
            sub.code            AS subject_code,
            d.name              AS department,
            sub.semester,
            COUNT(m.id)         AS total_students,
            COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) AS passed,
            ROUND(
                COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END)
                * 100.0 / NULLIF(COUNT(m.id), 0)::numeric, 2
            ) AS pass_rate
        FROM subjects sub
        LEFT JOIN departments d ON d.id = sub.department_id
        LEFT JOIN marks m ON m.subject_id = sub.id
        WHERE 1=1 {dept_filter}
        GROUP BY sub.name, sub.code, d.name, sub.semester
        HAVING COUNT(m.id) > 0
        ORDER BY pass_rate ASC
        LIMIT 20
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


async def _query_risk_distribution(db: AsyncSession, dept_name: Optional[str] = None) -> list[dict]:
    """Gather risk score distribution by department."""
    dept_filter = ""
    if dept_name:
        dept_filter = f"AND LOWER(d.name) = LOWER('{dept_name.replace(chr(39), chr(39)+chr(39))}')"

    sql = text(f"""
        SELECT
            d.name                  AS department,
            COUNT(*)                AS total,
            COUNT(CASE WHEN s.risk_score >= 81 THEN 1 END) AS critical,
            COUNT(CASE WHEN s.risk_score BETWEEN 61 AND 80 THEN 1 END) AS high,
            COUNT(CASE WHEN s.risk_score BETWEEN 31 AND 60 THEN 1 END) AS medium,
            COUNT(CASE WHEN s.risk_score < 31 THEN 1 END) AS low,
            ROUND(AVG(s.risk_score)::numeric, 2) AS avg_risk_score
        FROM students s
        LEFT JOIN departments d ON d.id = s.department_id
        WHERE 1=1 {dept_filter}
        GROUP BY d.name
        ORDER BY avg_risk_score DESC
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


async def _query_attendance_trend(db: AsyncSession, dept_name: Optional[str] = None) -> list[dict]:
    """Monthly attendance trend."""
    dept_filter = ""
    if dept_name:
        dept_filter = f"AND LOWER(d.name) = LOWER('{dept_name.replace(chr(39), chr(39)+chr(39))}')"

    sql = text(f"""
        SELECT
            TO_CHAR(a.date, 'YYYY-MM') AS month,
            ROUND(
                COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0
                / NULLIF(COUNT(*), 0)::numeric, 2
            ) AS attendance_pct,
            COUNT(DISTINCT a.student_id) AS student_count
        FROM attendance a
        LEFT JOIN students s ON s.id = a.student_id
        LEFT JOIN departments d ON d.id = s.department_id
        WHERE a.date >= NOW() - INTERVAL '6 months' {dept_filter}
        GROUP BY TO_CHAR(a.date, 'YYYY-MM')
        ORDER BY month ASC
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


async def _gather_report_data(
    db: AsyncSession,
    dept_name: Optional[str] = None,
) -> dict:
    """Collect all data sections for the report."""
    data = {}

    queries = [
        ("department_summary", _query_department_summary(db, dept_name)),
        ("subject_pass_rates", _query_subject_pass_rates(db, dept_name)),
        ("risk_distribution", _query_risk_distribution(db, dept_name)),
        ("attendance_trend", _query_attendance_trend(db, dept_name)),
    ]

    for key, coro in queries:
        try:
            data[key] = await coro
        except Exception as e:
            data[key] = []

    return data


async def report_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Report Agent V2."""
    llm = get_llm_provider()
    settings = get_settings()

    query = state.get("user_query", "")
    intent = state.get("intent", {})
    entities = intent.get("entities", {})

    # Determine scope
    departments = entities.get("departments", [])
    dept_filter: Optional[str] = departments[0] if departments else None

    # Determine report type from query
    query_lower = query.lower()
    if "hod" in query_lower:
        report_type = "HOD Report"
    elif "semester" in query_lower:
        report_type = "Semester Performance Report"
    elif "attendance" in query_lower:
        report_type = "Attendance Analysis Report"
    elif "risk" in query_lower or "at risk" in query_lower:
        report_type = "Student Risk Analysis Report"
    elif "naac" in query_lower:
        report_type = "NAAC Compliance Report"
    else:
        report_type = "Academic Performance Report"

    scope_label = f" — {dept_filter}" if dept_filter else " — All Departments"

    # ── Gather Data ──────────────────────────────────────────────────────────
    try:
        report_data = await _gather_report_data(db, dept_name=dept_filter)
    except Exception as e:
        return {
            "agent_used": "report",
            "error": f"Data gathering failed: {str(e)}",
            "final_response": f"Could not gather data for the report: {str(e)}",
            "insights": [],
            "recommendations": [],
        }

    # ── Generate Report with LLM ─────────────────────────────────────────────
    report_title = f"{report_type}{scope_label} — {datetime.now().strftime('%B %Y')}"

    messages = [{
        "role": "user",
        "content": (
            f"Generate a formal {report_type} titled: \"{report_title}\"\n\n"
            f"User request: '{query}'\n"
            f"Scope: {dept_filter or 'All departments'}\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"=== VERIFIED DATABASE DATA ===\n\n"
            f"Department Performance Summary:\n"
            f"{json.dumps(report_data.get('department_summary', []), indent=2, default=str)}\n\n"
            f"Subject Pass Rates (Bottom 20):\n"
            f"{json.dumps(report_data.get('subject_pass_rates', []), indent=2, default=str)}\n\n"
            f"Risk Distribution by Department:\n"
            f"{json.dumps(report_data.get('risk_distribution', []), indent=2, default=str)}\n\n"
            f"Attendance Trend (Last 6 Months):\n"
            f"{json.dumps(report_data.get('attendance_trend', []), indent=2, default=str)}\n\n"
            "Write the complete formal report. Use ONLY the data provided above. "
            "Do NOT fabricate any statistics."
        ),
    }]

    try:
        report_content = await llm.generate(
            messages=messages,
            system_prompt=REPORT_SYSTEM_PROMPT_V2,
            temperature=0.3,
            max_tokens=8192,
            model_name="llama-3.3-70b-versatile"
        )
        report_content = _strip_thinking(report_content)
    except Exception as e:
        error_msg = str(e) if str(e) else "LLM Generation timed out or failed."
        return {
            "agent_used": "report",
            "error": error_msg,
            "final_response": f"Report generation failed: {error_msg}",
            "insights": [],
            "recommendations": [],
        }

    # ── Generate PDF ─────────────────────────────────────────────────────────
    report_url: Optional[str] = None
    try:
        from app.utils.pdf_generator import generate_pdf
        os.makedirs(settings.reports_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{timestamp}.pdf"
        filepath = os.path.join(settings.reports_dir, filename)
        generate_pdf(filepath, report_title, report_content, report_data)
        report_url = f"/api/reports/download/{filename}"
    except Exception:
        pass  # Report content is still returned even without PDF

    # ── Build Insights ───────────────────────────────────────────────────────
    insights: list[str] = []
    dept_summary = report_data.get("department_summary", [])
    if dept_summary:
        try:
            best_att = max(dept_summary, key=lambda d: float(d.get("avg_attendance_pct") or 0))
            worst_att = min(dept_summary, key=lambda d: float(d.get("avg_attendance_pct") or 0))
            insights.append(
                f"Best attendance: {best_att['department']} at {best_att['avg_attendance_pct']:.1f}%. "
                f"Lowest: {worst_att['department']} at {worst_att['avg_attendance_pct']:.1f}%."
            )
        except (TypeError, ValueError, KeyError):
            pass

    subject_rates = report_data.get("subject_pass_rates", [])
    if subject_rates:
        failing = [s for s in subject_rates if float(s.get("pass_rate") or 100) < 50]
        if failing:
            insights.append(
                f"{len(failing)} subject(s) have pass rates below 50%, "
                f"led by '{failing[0].get('subject', 'Unknown')}' at {failing[0].get('pass_rate', 0):.1f}%."
            )

    recommendations: list[str] = [
        "Share this report with all HODs for departmental action plans.",
        "Schedule faculty review meeting to address subjects with low pass rates.",
    ]

    return {
        "agent_used": "report",
        "report_url": report_url,
        "insights": insights,
        "recommendations": recommendations,
        "final_response": report_content,
        "error": None,
    }
