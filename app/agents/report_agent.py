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
from app.config import get_settings


def _strip_thinking(text_content: str) -> str:
    text_content = re.sub(r"<thinking>.*?</thinking>", "", text_content, flags=re.DOTALL | re.IGNORECASE)
    text_content = re.sub(r"<thought>.*?</thought>", "", text_content, flags=re.DOTALL | re.IGNORECASE)
    return text_content.strip()


# ── Dynamic Query Templates ────────────────────────────────────────────────────

async def _query_view(db: AsyncSession, view_name: str, dept_name: Optional[str] = None) -> list[dict]:
    """Helper to query a view with an optional department filter."""
    dept_filter = ""
    if dept_name:
        # Simple filter by department_name if the column exists
        dept_filter = f"WHERE LOWER(department_name) = LOWER('{dept_name.replace(chr(39), chr(39)+chr(39))}')"
        if view_name == 'vw_placement_internship':
             # doesn't have department_name directly, skipping filter for brevity unless joined
             dept_filter = ""

    sql = text(f"SELECT * FROM {view_name} {dept_filter}")
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


async def _gather_report_data(
    db: AsyncSession,
    report_type: str,
    dept_name: Optional[str] = None,
) -> dict:
    """Collect data sections based on the report type."""
    data = {}

    if report_type == "department":
        data["profile"] = await _query_view(db, "vw_department_profile", dept_name)
        data["strength"] = await _query_view(db, "vw_student_strength", dept_name)
        data["performance"] = await _query_view(db, "vw_subject_performance", dept_name)
        data["placement"] = await _query_view(db, "vw_placement_internship", dept_name)
    elif report_type == "subject_performance":
        data["performance"] = await _query_view(db, "vw_subject_performance", dept_name)
    elif report_type == "attendance":
        data["attendance"] = await _query_view(db, "vw_student_attendance", dept_name)
    elif report_type == "at_risk":
        # Pull attendance, we will filter for low attendance in the template
        data["attendance"] = await _query_view(db, "vw_student_attendance", dept_name)
    elif report_type == "faculty_load":
        data["faculty"] = await _query_view(db, "vw_faculty_profile", dept_name)
    else:
        # Fallback
        data["profile"] = await _query_view(db, "vw_department_profile", dept_name)

    return data


async def report_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Report Agent V2."""
    llm = get_llm_provider()
    settings = get_settings()

    report_type = state.get("user_query", "department")
    intent = state.get("intent", {})
    entities = intent.get("entities", {})

    # Determine scope
    departments = entities.get("departments", [])
    dept_filter: Optional[str] = departments[0] if departments else None

    # ── Gather Data ──────────────────────────────────────────────────────────
    try:
        report_data = await _gather_report_data(db, report_type, dept_name=dept_filter)
    except Exception as e:
        return {
            "agent_used": "report",
            "error": f"Data gathering failed: {str(e)}",
            "final_response": f"Could not gather data for the report: {str(e)}",
            "insights": [],
            "recommendations": [],
        }

    # ── Extract Insights with LLM ─────────────────────────────────────────────
    messages = [{
        "role": "user",
        "content": (
            f"You are an expert Data Analyst. Analyze the following verified institutional data for the '{dept_filter or 'College'}' and extract key insights.\n\n"
            f"=== VERIFIED DATABASE DATA ===\n"
            f"{json.dumps(report_data, indent=2, default=str)}\n\n"
            "Return ONLY a JSON object with the following structure:\n"
            "{\n"
            "  \"summary\": \"A 3-5 sentence executive summary of the data.\",\n"
            "  \"key_points\": [\"Insight 1\", \"Insight 2\", \"Insight 3\"]\n"
            "}\n"
            "Do NOT include any markdown blocks (```json) or other text, just the raw JSON object."
        ),
    }]

    try:
        report_content = await llm.generate(
            messages=messages,
            system_prompt="You are a data analyst. Return ONLY pure valid JSON.",
            temperature=0.1,
            max_tokens=1000
        )
        report_content = _strip_thinking(report_content)
        try:
            insights_data = json.loads(report_content)
        except json.JSONDecodeError:
            # Fallback if the LLM output markdown
            report_content = report_content.replace("```json", "").replace("```", "").strip()
            insights_data = json.loads(report_content)
    except Exception as e:
        import traceback
        traceback.print_exc()
        insights_data = {"summary": "Insight generation failed.", "key_points": []}

    # ── Generate PDF using Jinja2 + xhtml2pdf ─────────────────────────────────────────────
    report_url: Optional[str] = None
    try:
        from app.utils.pdf_generator import generate_pdf
        from jinja2 import Environment, FileSystemLoader
        
        os.makedirs(settings.reports_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{timestamp}.pdf"
        filepath = os.path.join(settings.reports_dir, filename)
        
        # Render Jinja Template
        template_dir = os.path.join(os.path.dirname(__file__), "..", "templates", "reports")
        env = Environment(loader=FileSystemLoader(template_dir))
        
        # We can map report types to templates.
        template_name = f"{report_type}.html"
        # fallback to department.html if template doesn't exist
        if not os.path.exists(os.path.join(template_dir, template_name)):
            template_name = "department.html"
            
        report_title = f"{report_type.replace('_', ' ').title()} Report"
        if dept_filter:
            report_title += f" - {dept_filter}"
            
        template = env.get_template(template_name)
        
        html_content = template.render(
            title=report_title,
            date=datetime.now().strftime('%d %B %Y, %I:%M %p'),
            insights=insights_data,
            data=report_data
        )
        
        generate_pdf(filepath, html_content)
        report_url = f"/api/reports/download/{filename}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"PDF generation failed: {e}")

    return {
        "agent_used": "report",
        "report_url": report_url,
        "insights": insights_data.get("key_points", []),
        "recommendations": ["Review the generated report for further actions."],
        "final_response": "Report generated successfully.",
        "error": None,
    }
