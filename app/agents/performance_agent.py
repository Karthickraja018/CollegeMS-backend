"""
Performance Agent — button-triggered risk analysis.
Computes risk scores for all students and identifies at-risk cases.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import PERFORMANCE_SYSTEM_PROMPT


# Risk score weights
ATTENDANCE_WEIGHT = 0.4
MARKS_WEIGHT = 0.4
ARREAR_WEIGHT = 0.2

ATTENDANCE_THRESHOLD = 75.0  # Below this → flagged
MARKS_DECLINE_THRESHOLD = 20.0  # Percentage point drop → flagged
PASS_MARKS_THRESHOLD = 40.0  # Below this → at risk


async def _gather_student_metrics(db: AsyncSession) -> list[dict]:
    """Query all students with their attendance %, avg marks, and trend data."""
    sql = text("""
        WITH attendance_stats AS (
            SELECT
                s.id AS student_id,
                s.name,
                s.roll_number,
                s.semester,
                s.batch,
                d.name AS department,
                COUNT(*) AS total_classes,
                COUNT(CASE WHEN a.status = 'present' THEN 1 END) AS present_count,
                ROUND(
                    COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2
                ) AS attendance_pct
            FROM students s
            LEFT JOIN departments d ON d.id = s.department_id
            LEFT JOIN attendance a ON a.student_id = s.id
            GROUP BY s.id, s.name, s.roll_number, s.semester, s.batch, d.name
        ),
        marks_stats AS (
            SELECT
                m.student_id,
                ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0)), 2) AS avg_marks_pct,
                COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) < 40 THEN 1 END) AS subjects_below_pass
            FROM marks m
            GROUP BY m.student_id
        )
        SELECT
            a.student_id,
            a.name,
            a.roll_number,
            a.department,
            a.semester,
            a.batch,
            COALESCE(a.attendance_pct, 0) AS attendance_pct,
            COALESCE(ms.avg_marks_pct, 0) AS avg_marks_pct,
            COALESCE(ms.subjects_below_pass, 0) AS subjects_below_pass
        FROM attendance_stats a
        LEFT JOIN marks_stats ms ON ms.student_id = a.student_id
        ORDER BY a.department, a.name
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


def _compute_risk_score(student: dict) -> float:
    """
    Risk score 0-100:
    - Attendance component (0-40): inverse of attendance %
    - Marks component (0-40): inverse of avg marks %
    - Arrear component (0-20): based on subjects below pass
    """
    att_pct = float(student.get("attendance_pct") or 0)
    marks_pct = float(student.get("avg_marks_pct") or 0)
    arrears = int(student.get("subjects_below_pass") or 0)

    # Each component scored 0-1 (higher = worse)
    att_risk = max(0, (ATTENDANCE_THRESHOLD - att_pct) / ATTENDANCE_THRESHOLD) if att_pct < ATTENDANCE_THRESHOLD else 0
    marks_risk = max(0, (PASS_MARKS_THRESHOLD - marks_pct) / PASS_MARKS_THRESHOLD) if marks_pct < PASS_MARKS_THRESHOLD else 0
    arrear_risk = min(1.0, arrears / 5.0)  # Caps at 5 arrears = max risk

    score = (att_risk * ATTENDANCE_WEIGHT + marks_risk * MARKS_WEIGHT + arrear_risk * ARREAR_WEIGHT) * 100
    return round(score, 1)


def _risk_category(score: float) -> str:
    if score >= 81:
        return "CRITICAL"
    elif score >= 61:
        return "HIGH"
    elif score >= 31:
        return "MEDIUM"
    return "LOW"


async def performance_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Performance Agent (button-triggered, not scheduled)."""
    llm = get_llm_provider()

    # Gather data
    try:
        students = await _gather_student_metrics(db)
    except Exception as e:
        return {
            "agent_used": "performance",
            "error": f"Database error during analysis: {str(e)}",
            "final_response": f"Could not fetch student data: {str(e)}",
        }

    # Compute risk scores
    analyzed = []
    for s in students:
        score = _compute_risk_score(s)
        analyzed.append({
            **s,
            "risk_score": score,
            "risk_category": _risk_category(score),
        })

    # Sort by risk (highest first)
    analyzed.sort(key=lambda x: x["risk_score"], reverse=True)
    at_risk = [s for s in analyzed if s["risk_score"] > 30]

    # Save risk scores to DB
    try:
        for student in analyzed:
            await db.execute(
                text("UPDATE students SET risk_score = :score WHERE id = :id"),
                {"score": student["risk_score"], "id": student["student_id"]},
            )
        await db.commit()
    except Exception:
        pass  # Non-critical — analysis still proceeds

    # Build summary for LLM
    summary_data = {
        "total_students": len(analyzed),
        "at_risk_count": len(at_risk),
        "critical": len([s for s in analyzed if s["risk_category"] == "CRITICAL"]),
        "high": len([s for s in analyzed if s["risk_category"] == "HIGH"]),
        "medium": len([s for s in analyzed if s["risk_category"] == "MEDIUM"]),
        "top_at_risk": at_risk[:15],  # Limit LLM context
    }

    messages = [{"role": "user", "content": f"Here is the student performance analysis data:\n{str(summary_data)}\n\nProvide a concise analysis with recommendations."}]

    try:
        llm_analysis = await llm.generate(
            messages=messages,
            system_prompt=PERFORMANCE_SYSTEM_PROMPT,
            temperature=0.3,
        )
        # Strip thinking tags if the model outputs them
        import re
        llm_analysis = re.sub(r"<thinking>.*?</thinking>", "", llm_analysis, flags=re.DOTALL | re.IGNORECASE)
        llm_analysis = re.sub(r"<thought>.*?</thought>", "", llm_analysis, flags=re.DOTALL | re.IGNORECASE).strip()
    except Exception as e:
        llm_analysis = f"Analysis complete. {len(at_risk)} students identified as at-risk."

    return {
        "agent_used": "performance",
        "risk_analysis": {
            "total_students": len(analyzed),
            "at_risk_count": len(at_risk),
            "breakdown": {
                "critical": summary_data["critical"],
                "high": summary_data["high"],
                "medium": summary_data["medium"],
                "low": len(analyzed) - len(at_risk),
            },
            "at_risk_students": at_risk,
            "all_students": analyzed,
        },
        "final_response": llm_analysis,
        "error": None,
    }
