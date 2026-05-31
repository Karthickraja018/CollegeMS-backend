"""
Report Agent — orchestrates DB queries and generates PDF/DOCX reports.
"""
import json
import os
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import REPORT_SYSTEM_PROMPT
from app.config import get_settings


REPORT_QUERIES = {
    "department_summary": """
        SELECT
            d.name AS department,
            COUNT(DISTINCT s.id) AS total_students,
            ROUND(AVG(CASE WHEN a.status = 'present' THEN 100.0 ELSE 0 END), 2) AS avg_attendance_pct,
            ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0)), 2) AS avg_marks_pct
        FROM departments d
        LEFT JOIN students s ON s.department_id = d.id
        LEFT JOIN attendance a ON a.student_id = s.id
        LEFT JOIN marks m ON m.student_id = s.id
        GROUP BY d.name
        ORDER BY d.name
    """,
    "at_risk_summary": """
        SELECT
            d.name AS department,
            COUNT(CASE WHEN s.risk_score >= 61 THEN 1 END) AS high_risk,
            COUNT(CASE WHEN s.risk_score BETWEEN 31 AND 60 THEN 1 END) AS medium_risk,
            COUNT(CASE WHEN s.risk_score < 31 THEN 1 END) AS low_risk
        FROM students s
        LEFT JOIN departments d ON d.id = s.department_id
        GROUP BY d.name
        ORDER BY d.name
    """,
    "subject_pass_rate": """
        SELECT
            sub.name AS subject,
            d.name AS department,
            sub.semester,
            COUNT(m.id) AS total_students,
            COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) AS passed,
            ROUND(
                COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) * 100.0 / NULLIF(COUNT(m.id), 0), 2
            ) AS pass_rate
        FROM subjects sub
        LEFT JOIN departments d ON d.id = sub.department_id
        LEFT JOIN marks m ON m.subject_id = sub.id
        GROUP BY sub.name, d.name, sub.semester
        ORDER BY pass_rate ASC
        LIMIT 20
    """,
}


async def _gather_report_data(db: AsyncSession) -> dict:
    """Run all report queries and return structured data."""
    data = {}
    for key, sql in REPORT_QUERIES.items():
        try:
            result = await db.execute(text(sql))
            rows = result.fetchall()
            cols = list(result.keys())
            data[key] = [dict(zip(cols, row)) for row in rows]
        except Exception as e:
            data[key] = []
    return data


async def report_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Report Agent."""
    llm = get_llm_provider()
    settings = get_settings()
    query = state.get("user_query", "")

    # Gather verified data from DB
    try:
        report_data = await _gather_report_data(db)
    except Exception as e:
        return {
            "agent_used": "report",
            "error": f"Data gathering failed: {str(e)}",
            "final_response": f"Could not gather data for report: {str(e)}",
        }

    # Ask LLM to write the report narrative
    messages = [
        {
            "role": "user",
            "content": (
                f"Generate a comprehensive academic report for the request: '{query}'\n\n"
                f"Verified database data:\n{json.dumps(report_data, indent=2, default=str)}\n\n"
                "Write the full report with all sections."
            ),
        }
    ]

    try:
        report_content = await llm.generate(
            messages=messages,
            system_prompt=REPORT_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=8192,
        )
        # Strip thinking tags if the model outputs them
        import re
        report_content = re.sub(r"<thinking>.*?</thinking>", "", report_content, flags=re.DOTALL | re.IGNORECASE)
        report_content = re.sub(r"<thought>.*?</thought>", "", report_content, flags=re.DOTALL | re.IGNORECASE).strip()
    except Exception as e:
        return {
            "agent_used": "report",
            "error": str(e),
            "final_response": f"Report generation failed: {str(e)}",
        }

    # Generate PDF
    try:
        from app.utils.pdf_generator import generate_pdf
        report_title = f"Academic Report — {datetime.now().strftime('%B %Y')}"
        os.makedirs(settings.reports_dir, exist_ok=True)
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = os.path.join(settings.reports_dir, filename)
        generate_pdf(filepath, report_title, report_content, report_data)
        report_url = f"/api/reports/download/{filename}"
    except Exception as e:
        report_url = None

    return {
        "agent_used": "report",
        "report_url": report_url,
        "final_response": report_content,
        "error": None,
    }
