"""
Performance Agent V2 — Risk scoring with explanations, trend analysis, and dept-scoped analysis.
Computes risk scores for students and generates detailed, human-readable risk reports.
"""
from __future__ import annotations

import re
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.llm.provider_factory import get_llm_provider
from app.prompts import PERFORMANCE_SYSTEM_PROMPT_V2


# ── Risk Score Weights ─────────────────────────────────────────────────────────
ATTENDANCE_WEIGHT = 0.40
MARKS_WEIGHT = 0.40
ARREAR_WEIGHT = 0.20

# ── Thresholds ─────────────────────────────────────────────────────────────────
ATTENDANCE_THRESHOLD = 75.0    # Below this → flagged
ATTENDANCE_CRITICAL = 50.0     # Below this → critical risk contributor
PASS_MARKS_THRESHOLD = 40.0    # Below this → at risk
MARKS_CRITICAL = 25.0          # Below this → critical risk contributor
MAX_ARREARS_FOR_FULL_RISK = 5  # 5+ arrears = max arrear component

async def _load_thresholds(db: AsyncSession) -> dict:
    """Load dynamic thresholds from colleges.settings."""
    r = await db.execute(text("SELECT settings FROM colleges LIMIT 1"))
    settings = r.scalar() or {}
    return {
        "attendance_threshold": float(settings.get("attendance_threshold", ATTENDANCE_THRESHOLD)),
        "pass_marks_threshold": float(settings.get("pass_mark_threshold", PASS_MARKS_THRESHOLD)),
        "risk_score_threshold": float(settings.get("risk_score_threshold", 60.0)),
    }


def _strip_thinking(text: str) -> str:
    """Remove <thinking>/<thought> blocks from model output."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


async def _gather_student_metrics(
    db: AsyncSession,
    department_name: Optional[str] = None,
    semester: Optional[int] = None,
) -> list[dict]:
    """
    Gather comprehensive student metrics.
    Optionally scoped to a specific department or semester.
    """
    params = {}
    dept_clause = ""
    if department_name:
        dept_clause = "AND LOWER(d.code) = LOWER(:dept_code)"
        params["dept_code"] = department_name

    sem_clause = ""
    if semester:
        sem_clause = "AND s.current_semester = :semester"
        params["semester"] = int(semester)

    sql = text(f"""
        WITH attendance_stats AS (
            SELECT
                s.id                  AS student_id,
                s.name,
                s.roll_number,
                s.current_semester    AS semester,
                s.batch,
                s.section,
                d.name                AS department,
                d.code                AS dept_code,
                COUNT(a.id)           AS total_classes,
                COUNT(CASE WHEN a.status = 'present' THEN 1 END) AS present_count,
                ROUND(
                    COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0
                    / NULLIF(COUNT(a.id), 0)::numeric, 2
                ) AS attendance_pct
            FROM students s
            LEFT JOIN departments d ON d.id = s.department_id
            LEFT JOIN attendance_records a ON a.student_id = s.id
            WHERE 1=1 {dept_clause} {sem_clause}
            GROUP BY s.id, s.name, s.roll_number, s.current_semester, s.batch, s.section, d.name, d.code
        ),
        marks_stats AS (
            SELECT
                m.student_id,
                ROUND(AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0))::numeric, 2)
                    AS avg_marks_pct,
                COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) < 40 THEN 1 END)
                    AS subjects_below_pass,
                COUNT(DISTINCT m.subject_id) AS total_subjects
            FROM marks_records m
            GROUP BY m.student_id
        )
        SELECT
            a.student_id,
            a.name,
            a.roll_number,
            a.department,
            a.dept_code,
            a.semester,
            a.batch,
            a.section,
            a.total_classes,
            COALESCE(a.attendance_pct, 0)           AS attendance_pct,
            COALESCE(ms.avg_marks_pct, 0)            AS avg_marks_pct,
            COALESCE(ms.subjects_below_pass, 0)      AS subjects_below_pass,
            COALESCE(ms.total_subjects, 0)           AS total_subjects
        FROM attendance_stats a
        LEFT JOIN marks_stats ms ON ms.student_id = a.student_id
        ORDER BY a.department, a.semester, a.name
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()
    return [dict(zip(result.keys(), row)) for row in rows]


def _compute_risk_score(student: dict, thresholds: dict) -> float:
    """
    Compute risk score 0-100.
    Higher score = higher risk.

    Uses non-linear scaling so students with MULTIPLE risk factors
    (low attendance + low marks + arrears) correctly score HIGH/CRITICAL.

    Components:
    - Attendance risk (0-40): quadratic scaling below threshold
    - Marks risk (0-40): quadratic scaling below pass threshold
    - Arrear risk (0-20): proportional to number of failed subjects
    - Multi-factor bonus: +10 when BOTH attendance and marks are below threshold
    """
    att_pct = float(student.get("attendance_pct") or 0)
    marks_pct = float(student.get("avg_marks_pct") or 0)
    arrears = int(student.get("subjects_below_pass") or 0)

    att_thresh = thresholds.get("attendance_threshold", ATTENDANCE_THRESHOLD)
    pass_thresh = thresholds.get("pass_marks_threshold", PASS_MARKS_THRESHOLD)

    # Attendance component: quadratic for faster rise as attendance drops
    if att_pct < att_thresh:
        raw_att = (att_thresh - att_pct) / att_thresh
        att_risk = raw_att ** 0.7  # sub-linear → rises faster than linear
    else:
        att_risk = 0.0

    # Marks component: quadratic for faster rise as marks drop
    if marks_pct < pass_thresh:
        raw_marks = (pass_thresh - marks_pct) / pass_thresh
        marks_risk = raw_marks ** 0.7
    else:
        marks_risk = 0.0

    # Arrear component: linear, capped at MAX_ARREARS_FOR_FULL_RISK
    arrear_risk = min(1.0, arrears / MAX_ARREARS_FOR_FULL_RISK)

    base_score = (
        att_risk * ATTENDANCE_WEIGHT
        + marks_risk * MARKS_WEIGHT
        + arrear_risk * ARREAR_WEIGHT
    ) * 100

    # Multi-factor penalty: student has BOTH attendance AND marks below threshold
    multi_factor_penalty = 0.0
    if att_pct < att_thresh and marks_pct < pass_thresh:
        multi_factor_penalty = 10.0
    # Extra penalty for critical levels
    if att_pct < ATTENDANCE_CRITICAL or marks_pct < MARKS_CRITICAL:
        multi_factor_penalty += 8.0

    score = min(100.0, base_score + multi_factor_penalty)
    return round(score, 1)


def _risk_category(score: float) -> str:
    """Map score to risk level."""
    if score >= 81:
        return "CRITICAL"
    elif score >= 61:
        return "HIGH"
    elif score >= 31:
        return "MEDIUM"
    return "LOW"


def _build_risk_explanation(student: dict, thresholds: dict) -> str:
    """
    Generate a human-readable explanation of why a student has their risk score.
    e.g.: "Attendance 58% (below 75%), Average marks 32% (below 40%), 3 active arrears"
    """
    reasons: list[str] = []

    att_pct = float(student.get("attendance_pct") or 0)
    marks_pct = float(student.get("avg_marks_pct") or 0)
    arrears = int(student.get("subjects_below_pass") or 0)

    att_thresh = thresholds.get("attendance_threshold", ATTENDANCE_THRESHOLD)
    pass_thresh = thresholds.get("pass_marks_threshold", PASS_MARKS_THRESHOLD)

    if att_pct < att_thresh:
        reasons.append(f"Attendance {att_pct:.1f}% (below {att_thresh:.0f}% threshold)")

    if marks_pct < pass_thresh:
        reasons.append(f"Average marks {marks_pct:.1f}% (below {pass_thresh:.0f}% pass mark)")

    if arrears > 0:
        reasons.append(f"{arrears} active arrear{'s' if arrears != 1 else ''}")

    if not reasons:
        return "Student is generally performing well."

    return " | ".join(reasons)


def _build_department_summary(analyzed: list[dict]) -> dict[str, dict]:
    """Aggregate risk data by department."""
    dept_data: dict[str, dict] = {}

    for student in analyzed:
        dept = student.get("department", "Unknown")
        if dept not in dept_data:
            dept_data[dept] = {
                "department": dept,
                "total": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "avg_attendance": 0.0,
                "avg_marks": 0.0,
                "_att_sum": 0.0,
                "_marks_sum": 0.0,
            }

        d = dept_data[dept]
        d["total"] += 1
        category = student.get("risk_category", "LOW").upper()
        d[category.lower()] = d.get(category.lower(), 0) + 1
        d["_att_sum"] += float(student.get("attendance_pct") or 0)
        d["_marks_sum"] += float(student.get("avg_marks_pct") or 0)

    # Compute averages and clean up
    for dept, d in dept_data.items():
        total = d["total"]
        if total > 0:
            d["avg_attendance"] = round(d["_att_sum"] / total, 1)
            d["avg_marks"] = round(d["_marks_sum"] / total, 1)
        del d["_att_sum"]
        del d["_marks_sum"]

    return dept_data


async def performance_agent_node(state: AgentState, db: AsyncSession) -> dict:
    """LangGraph node: Performance Agent V2."""
    llm = get_llm_provider()
    intent = state.get("intent", {})
    entities = intent.get("entities", {})

    # Check if query is scoped to a specific department or semester
    departments = entities.get("departments", [])
    department_filter = departments[0] if departments else None
    semester_filter: Optional[int] = None  # Could be extended to parse from intent

    # ── Gather Data ──────────────────────────────────────────────────────────
    thresholds = await _load_thresholds(db)
    
    try:
        students = await _gather_student_metrics(
            db,
            department_name=department_filter,
            semester=semester_filter,
        )
    except Exception as e:
        return {
            "agent_used": "performance",
            "error": f"Database error during analysis: {str(e)}",
            "final_response": f"Could not fetch student performance data: {str(e)}",
            "insights": [],
            "recommendations": [],
        }

    if not students:
        scope_desc = f" for {department_filter}" if department_filter else ""
        return {
            "agent_used": "performance",
            "risk_analysis": None,
            "final_response": f"No student data found{scope_desc}. Please ensure data has been uploaded.",
            "insights": ["No student data available for risk analysis."],
            "recommendations": [],
            "error": None,
        }

    # ── Compute Risk Scores ──────────────────────────────────────────────────
    analyzed: list[dict] = []
    for s in students:
        score = _compute_risk_score(s, thresholds)
        analyzed.append({
            **s,
            "risk_score": score,
            "risk_category": _risk_category(score),
            "risk_explanation": _build_risk_explanation(s, thresholds),
        })

    # Sort by risk (highest first)
    analyzed.sort(key=lambda x: x["risk_score"], reverse=True)
    at_risk = [s for s in analyzed if s["risk_score"] > 30]
    critical = [s for s in analyzed if s["risk_category"] == "CRITICAL"]
    high = [s for s in analyzed if s["risk_category"] == "HIGH"]
    medium = [s for s in analyzed if s["risk_category"] == "MEDIUM"]
    low_risk = [s for s in analyzed if s["risk_category"] == "LOW"]

    # ── Department Breakdown ─────────────────────────────────────────────────
    dept_summary = _build_department_summary(analyzed)

    # ── Persist Risk Scores ──────────────────────────────────────────────────
    try:
        for student in analyzed:
            await db.execute(
                text("UPDATE students SET risk_score = :score WHERE id = :id"),
                {"score": student["risk_score"], "id": student["student_id"]},
            )
        await db.commit()
    except Exception:
        pass  # Non-critical — analysis still proceeds

    # ── Build Context for LLM ────────────────────────────────────────────────
    scope_label = f" ({department_filter})" if department_filter else ""
    summary_data = {
        "scope": department_filter or "All departments",
        "total_students": len(analyzed),
        "at_risk_count": len(at_risk),
        "risk_breakdown": {
            "critical": len(critical),
            "high": len(high),
            "medium": len(medium),
            "low": len(low_risk),
        },
        "department_summary": list(dept_summary.values()),
        "top_critical_students": [
            {
                "name": s["name"],
                "roll_number": s["roll_number"],
                "department": s["department"],
                "semester": s["semester"],
                "risk_score": s["risk_score"],
                "risk_category": s["risk_category"],
                "explanation": s["risk_explanation"],
                "attendance_pct": s["attendance_pct"],
                "avg_marks_pct": s["avg_marks_pct"],
                "arrears": s["subjects_below_pass"],
            }
            for s in analyzed[:20]  # Top 20 highest risk for LLM context
        ],
    }

    # ── LLM Analysis ─────────────────────────────────────────────────────────
    import json
    from app.agents.nlp_sql_mcp.tools.db_tools import tool_search_schema
    schema_context = tool_search_schema("students departments attendance_records marks_records")
    
    messages = [{
        "role": "user",
        "content": (
            f"Database Schema Context (via MCP Tools):\n{schema_context}\n\n"
            f"Performance analysis data{scope_label}:\n"
            f"{json.dumps(summary_data, indent=2, default=str)}\n\n"
            "Generate a comprehensive risk analysis report with insights and recommendations."
        )
    }]

    try:
        llm_analysis = await llm.generate(
            messages=messages,
            system_prompt=PERFORMANCE_SYSTEM_PROMPT_V2,
            temperature=0.3,
            model_name="llama-3.3-70b-versatile"
        )
        llm_analysis = _strip_thinking(llm_analysis)
    except Exception as e:
        llm_analysis = (
            f"Performance analysis complete.\n\n"
            f"**Summary**: {len(analyzed)} students analyzed. "
            f"{len(at_risk)} at risk ({len(critical)} critical, {len(high)} high, {len(medium)} medium).\n\n"
            f"**Top risk factors**: Low attendance and poor marks are the primary drivers."
        )

    # ── Build Insights ───────────────────────────────────────────────────────
    insights: list[str] = []
    if analyzed:
        risk_pct = round(len(at_risk) / len(analyzed) * 100, 1)
        insights.append(
            f"{len(at_risk)} of {len(analyzed)} students ({risk_pct}%) are at risk."
        )
    if critical:
        insights.append(
            f"{len(critical)} students are in CRITICAL status requiring immediate intervention."
        )
    if dept_summary:
        worst_dept = max(
            dept_summary.values(),
            key=lambda d: d.get("critical", 0) + d.get("high", 0),
        )
        insights.append(
            f"{worst_dept['department']} has the highest number of at-risk students "
            f"({worst_dept.get('critical',0) + worst_dept.get('high',0)} critical/high risk)."
        )

    recommendations: list[str] = []
    if critical:
        recommendations.append(
            f"Immediately counsel {len(critical)} CRITICAL students and notify their parents."
        )
    if high:
        recommendations.append(
            f"Assign faculty mentors to {len(high)} HIGH-risk students for weekly check-ins."
        )
    if medium:
        recommendations.append(
            f"Enroll {len(medium)} MEDIUM-risk students in peer tutoring programs."
        )

    return {
        "agent_used": "performance",
        "risk_analysis": {
            "total_students": len(analyzed),
            "at_risk_count": len(at_risk),
            "breakdown": {
                "critical": len(critical),
                "high": len(high),
                "medium": len(medium),
                "low": len(low_risk),
            },
            "department_summary": list(dept_summary.values()),
            "at_risk_students": [
                {
                    "name": s["name"],
                    "roll_number": s["roll_number"],
                    "department": s["department"],
                    "semester": s["semester"],
                    "risk_score": s["risk_score"],
                    "risk_category": s["risk_category"],
                    "risk_explanation": s["risk_explanation"],
                    "attendance_pct": float(s["attendance_pct"]),
                    "avg_marks_pct": float(s["avg_marks_pct"]),
                    "subjects_below_pass": int(s["subjects_below_pass"]),
                }
                for s in at_risk
            ],
            "all_students": analyzed,
        },
        "insights": insights,
        "recommendations": recommendations,
        "final_response": llm_analysis,
        "error": None,
    }
