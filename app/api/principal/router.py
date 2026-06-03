"""
Principal Intelligence API Router — Faculty & HOD Intelligence Endpoints.

Endpoints:
  GET /api/principal/dashboard              — institution KPIs
  GET /api/principal/executive-summary      — AI summary
  GET /api/principal/departments            — department list with health
  GET /api/principal/risk-students          — at-risk students (mocked legacy)
  GET /api/principal/risk-summary           — risk counts
  GET /api/principal/accreditation          — NAAC/NBA readiness

  [NEW] Faculty Intelligence
  GET /api/principal/faculty                — all faculty with latest performance
  GET /api/principal/faculty/compliance     — non-compliant faculty
  GET /api/principal/faculty/rankings       — top/bottom performers
  GET /api/principal/faculty/{user_id}      — single faculty profile + 6-month trend

  [NEW] HOD Intelligence
  GET /api/principal/hod                    — all HODs with scores
  GET /api/principal/hod/rankings           — HOD ranking
  GET /api/principal/hod/{user_id}          — HOD profile + dept trend

  [NEW] Underperforming Students by Staff
  GET /api/principal/departments/{dept_id}/underperforming
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole

router = APIRouter(prefix="/principal", tags=["principal"])

# Principal role required
get_principal = require_roles(UserRole.admin, UserRole.principal)


# ══════════════════════════════════════════════════════════════════════════════
# EXISTING ENDPOINTS (preserved)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_principal_dashboard(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Compute real institution-wide KPIs for the principal dashboard."""
    r = await db.execute(text("""
        SELECT
            ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_attendance,
            ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
            COUNT(DISTINCT s.id) AS total_students,
            COUNT(DISTINCT s.id) FILTER (WHERE s.risk_score >= 60) AS risk_students
        FROM students s
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
        WHERE s.status = 'active'
    """))
    row = r.fetchone()
    faculty_r = await db.execute(text("SELECT COUNT(*) FROM users WHERE role IN ('faculty', 'hod') AND is_active = TRUE"))
    faculty_count = faculty_r.scalar() or 0
    return {
        "academic_health": 0,
        "attendance": float(row[0] or 0) if row else 0,
        "pass_rate": float(row[1] or 0) if row else 0,
        "placement_rate": 0,
        "risk_students": int(row[3] or 0) if row else 0,
        "faculty_count": faculty_count
    }


@router.get("/executive-summary")
async def get_executive_summary(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    return {
        "summary": "Institution performance remains stable. CSE department leads in attendance, but ECE requires attention due to a recent dip in pass rates. NBA documentation is 91% complete."
    }


@router.get("/departments")
async def get_departments(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    r = await db.execute(text("""
        SELECT
            d.id, d.name, d.code,
            COUNT(DISTINCT s.id) AS total_students,
            ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_attendance,
            ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
            COUNT(DISTINCT s.id) FILTER (WHERE s.risk_score >= 60) AS risk_students,
            COUNT(DISTINCT u.id) AS faculty_count
        FROM departments d
        LEFT JOIN students s ON s.department_id = d.id AND s.status = 'active'
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
        LEFT JOIN users u ON u.department_id = d.id AND u.role IN ('faculty','hod') AND u.is_active = TRUE
        WHERE d.is_active = TRUE
        GROUP BY d.id, d.name, d.code
        ORDER BY d.name
    """))
    rows = r.fetchall()
    result = []
    for row in rows:
        total = row[3] or 1
        risk = row[6] or 0
        att = float(row[4] or 0)
        pass_r = float(row[5] or 0)
        health = round(att * 0.40 + pass_r * 0.40 + ((1 - risk/total) * 100) * 0.20, 1)
        result.append({
            "department_id": row[0],
            "department": row[1],
            "code": row[2],
            "total_students": row[3] or 0,
            "attendance": att,
            "pass_rate": pass_r,
            "risk_students": risk,
            "faculty_count": row[7] or 0,
            "health_score": min(100, max(0, health)),
        })
    return result


@router.get("/risk-students")
async def get_risk_students(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    r = await db.execute(text("""
        SELECT s.id, s.name, d.name AS department, s.roll_number,
               s.risk_score, s.current_semester,
               ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
               CASE
                   WHEN s.risk_score >= 80 THEN 'critical'
                   WHEN s.risk_score >= 60 THEN 'high'
                   WHEN s.risk_score >= 40 THEN 'medium'
                   ELSE 'low'
               END AS risk_level
        FROM students s
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE s.status = 'active' AND s.risk_score >= 60
        ORDER BY s.risk_score DESC
        LIMIT 20
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    return [dict(zip(cols, row)) for row in rows]


@router.get("/risk-summary")
async def get_risk_summary(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    r = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE risk_score >= 80) AS critical,
            COUNT(*) FILTER (WHERE risk_score >= 60 AND risk_score < 80) AS high,
            COUNT(*) FILTER (WHERE risk_score >= 40 AND risk_score < 60) AS medium,
            COUNT(*) FILTER (WHERE risk_score < 40) AS low,
            COUNT(*) AS total
        FROM students WHERE status = 'active'
    """))
    row = r.fetchone()
    return {
        "critical": row[0] or 0,
        "high": row[1] or 0,
        "medium": row[2] or 0,
        "low": row[3] or 0,
        "total": row[4] or 0,
    }


@router.get("/accreditation")
async def get_accreditation(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Compute accreditation readiness from real academic data."""
    r = await db.execute(text("""
        SELECT
            ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_att,
            ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
            COUNT(*) FILTER (WHERE s.risk_score >= 60) AS at_risk,
            COUNT(*) AS total
        FROM students s
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
        WHERE s.status = 'active'
    """))
    row = r.fetchone()
    if not row:
        return {"nba_readiness": 0, "naac_readiness": 0, "documentation": 76}

    avg_att = float(row[0] or 0)
    pass_rate = float(row[1] or 0)
    at_risk = int(row[2] or 0)
    total = int(row[3] or 1)
    risk_ratio = 1 - (at_risk / total)

    naac_readiness = min(100, round(avg_att * 0.40 + pass_rate * 0.40 + risk_ratio * 100 * 0.20))
    nba_readiness = min(100, round(avg_att * 0.35 + pass_rate * 0.50 + risk_ratio * 100 * 0.15))

    return {
        "nba_readiness": nba_readiness,
        "naac_readiness": naac_readiness,
        "documentation": 76
    }


@router.post("/ai-query")
async def principal_ai_query(
    query: dict,
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    from app.agents.principal_agent import run_principal_agent
    text_q = query.get("query", "")
    response = await run_principal_agent(text_q, current_user.college_id, db)
    return {"response": response}


@router.post("/recommendations")
async def generate_recommendations(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    return {
        "recommendations": [
            "Schedule an attendance review meeting with ECE HOD.",
            "Accelerate NBA criteria 3 documentation for CSE.",
            "Review critical risk students in MECH department."
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: FACULTY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/faculty")
async def list_faculty(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """All faculty with their latest performance metrics and live academic outcomes."""
    r = await db.execute(text("""
        SELECT
            u.id, u.full_name, u.email, u.employee_id, u.designation,
            u.experience_years, u.qualification, u.role,
            d.id AS dept_id, d.name AS dept_name, d.code AS dept_code,
            -- Latest month performance metrics
            spm.attendance_submission_pct,
            spm.marks_submission_pct,
            spm.student_pass_rate AS metric_pass_rate,
            spm.avg_student_attendance AS metric_avg_att,
            spm.feedback_score,
            spm.classes_conducted,
            spm.ai_usage_count,
            spm.report_count,
            spm.month AS latest_month,
            -- Live outcomes from actual student data
            ROUND(AVG(att.attendance_pct)::numeric, 1) AS live_student_att,
            ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS live_pass_rate,
            COUNT(DISTINCT fsa.subject_id) AS subjects_count,
            COUNT(DISTINCT mr.student_id) AS students_taught
        FROM users u
        JOIN departments d ON d.id = u.department_id
        LEFT JOIN LATERAL (
            SELECT * FROM staff_performance_metrics s2
            WHERE s2.user_id = u.id
            ORDER BY s2.month DESC
            LIMIT 1
        ) spm ON TRUE
        LEFT JOIN faculty_subject_assignments fsa ON fsa.user_id = u.id
        LEFT JOIN marks_records mr ON mr.subject_id = fsa.subject_id AND mr.is_absent = FALSE
        LEFT JOIN students s ON s.id = mr.student_id AND s.status = 'active'
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE u.role IN ('faculty', 'hod') AND u.is_active = TRUE AND u.department_id IS NOT NULL
        GROUP BY u.id, u.full_name, u.email, u.employee_id, u.designation,
                 u.experience_years, u.qualification, u.role,
                 d.id, d.name, d.code,
                 spm.attendance_submission_pct, spm.marks_submission_pct,
                 spm.student_pass_rate, spm.avg_student_attendance, spm.feedback_score,
                 spm.classes_conducted, spm.ai_usage_count, spm.report_count, spm.month
        ORDER BY d.name, u.full_name
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    faculty_list = []
    for row in rows:
        data = dict(zip(cols, row))
        # Compute compliance score
        att_sub = float(data.get("attendance_submission_pct") or 0)
        marks_sub = float(data.get("marks_submission_pct") or 0)
        compliance = round((att_sub + marks_sub) / 2, 1) if (att_sub or marks_sub) else None
        data["compliance_score"] = compliance
        # Performance grade
        pass_r = float(data.get("live_pass_rate") or data.get("metric_pass_rate") or 0)
        if pass_r >= 80:
            grade, grade_color = "Excellent", "green"
        elif pass_r >= 65:
            grade, grade_color = "Good", "blue"
        elif pass_r >= 50:
            grade, grade_color = "Needs Attention", "amber"
        else:
            grade, grade_color = "Critical", "red"
        data["performance_grade"] = grade
        data["performance_color"] = grade_color
        faculty_list.append(data)
    return faculty_list


@router.get("/faculty/compliance")
async def get_faculty_compliance(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Faculty who are non-compliant (late attendance/marks submission, low activity)."""
    r = await db.execute(text("""
        SELECT
            u.id, u.full_name, u.employee_id, u.designation,
            d.name AS dept_name,
            spm.attendance_submission_pct,
            spm.marks_submission_pct,
            spm.student_pass_rate,
            spm.month AS latest_month
        FROM users u
        JOIN departments d ON d.id = u.department_id
        LEFT JOIN LATERAL (
            SELECT * FROM staff_performance_metrics s2
            WHERE s2.user_id = u.id
            ORDER BY s2.month DESC
            LIMIT 1
        ) spm ON TRUE
        WHERE u.role IN ('faculty', 'hod') AND u.is_active = TRUE
          AND u.department_id IS NOT NULL
          AND (
              spm.attendance_submission_pct < 80
              OR spm.marks_submission_pct < 80
              OR spm.student_pass_rate < 55
              OR spm.id IS NULL
          )
        ORDER BY spm.attendance_submission_pct ASC NULLS FIRST
        LIMIT 20
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    result = []
    for row in rows:
        data = dict(zip(cols, row))
        issues = []
        att_sub = float(data.get("attendance_submission_pct") or 0)
        marks_sub = float(data.get("marks_submission_pct") or 0)
        pass_r = float(data.get("student_pass_rate") or 0)
        if data.get("latest_month") is None:
            issues.append("No performance data recorded")
        if att_sub < 80:
            issues.append(f"Attendance submission: {att_sub}% (below 80%)")
        if marks_sub < 80:
            issues.append(f"Marks submission: {marks_sub}% (below 80%)")
        if pass_r < 55:
            issues.append(f"Student pass rate: {pass_r}% (below 55%)")
        data["issues"] = issues
        result.append(data)
    return result


@router.get("/faculty/rankings")
async def get_faculty_rankings(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Top and bottom performing faculty based on latest metrics."""
    r = await db.execute(text("""
        SELECT
            u.id, u.full_name, u.employee_id, u.designation,
            d.name AS dept_name, d.code AS dept_code,
            spm.student_pass_rate,
            spm.attendance_submission_pct,
            spm.marks_submission_pct,
            spm.feedback_score,
            spm.month AS latest_month
        FROM users u
        JOIN departments d ON d.id = u.department_id
        LEFT JOIN LATERAL (
            SELECT * FROM staff_performance_metrics s2
            WHERE s2.user_id = u.id
            ORDER BY s2.month DESC
            LIMIT 1
        ) spm ON TRUE
        WHERE u.role IN ('faculty', 'hod') AND u.is_active = TRUE AND u.department_id IS NOT NULL
          AND spm.id IS NOT NULL
        ORDER BY spm.student_pass_rate DESC NULLS LAST
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    all_faculty = [dict(zip(cols, row)) for row in rows]
    return {
        "top_performers": all_faculty[:5],
        "bottom_performers": list(reversed(all_faculty[-5:])) if len(all_faculty) >= 5 else all_faculty,
        "total": len(all_faculty),
    }


@router.get("/faculty/{user_id}")
async def get_faculty_profile(
    user_id: int,
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Full faculty profile with 6-month performance trend and student outcomes."""
    # Faculty info
    r = await db.execute(text("""
        SELECT u.id, u.full_name, u.email, u.employee_id, u.designation,
               u.experience_years, u.qualification, u.phone, u.role, u.last_login,
               d.id AS dept_id, d.name AS dept_name, d.code AS dept_code
        FROM users u
        JOIN departments d ON d.id = u.department_id
        WHERE u.id = :uid AND u.role IN ('faculty','hod') AND u.is_active = TRUE
    """), {"uid": user_id})
    fac = r.fetchone()
    if not fac:
        raise HTTPException(status_code=404, detail="Faculty not found")
    fac_dict = dict(zip(r.keys(), fac))

    # 6-month performance trend
    r = await db.execute(text("""
        SELECT month, attendance_submission_pct, marks_submission_pct,
               student_pass_rate, avg_student_attendance, feedback_score,
               classes_conducted, ai_usage_count, report_count
        FROM staff_performance_metrics
        WHERE user_id = :uid
        ORDER BY month ASC
        LIMIT 6
    """), {"uid": user_id})
    trend_rows = r.fetchall()
    trend = [dict(zip(r.keys(), row)) for row in trend_rows]

    # Subjects taught
    r = await db.execute(text("""
        SELECT sub.id, sub.name, sub.code, sub.semester_number,
               COUNT(DISTINCT mr.student_id) AS students_taught,
               ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric,1) AS pass_rate,
               ROUND(AVG(mr.percentage)::numeric,1) AS avg_marks
        FROM faculty_subject_assignments fsa
        JOIN subjects sub ON sub.id = fsa.subject_id
        LEFT JOIN marks_records mr ON mr.subject_id = sub.id AND mr.is_absent = FALSE
        WHERE fsa.user_id = :uid
        GROUP BY sub.id, sub.name, sub.code, sub.semester_number
        ORDER BY sub.semester_number, pass_rate ASC NULLS LAST
    """), {"uid": user_id})
    subj_rows = r.fetchall()
    subjects = [dict(zip(r.keys(), row)) for row in subj_rows]

    # Fetch college settings for dynamic thresholds
    r = await db.execute(text("SELECT settings FROM colleges WHERE id = :college_id"), {"college_id": current_user.college_id})
    settings = r.scalar() or {}
    pass_mark_threshold = float(settings.get("pass_mark_threshold", 50))
    attendance_threshold = float(settings.get("attendance_threshold", 75))
    risk_score_threshold = float(settings.get("risk_score_threshold", 60))

    # 1. Globally At-Risk Students
    r = await db.execute(text("""
        SELECT DISTINCT s.id, s.name, s.roll_number, s.current_semester,
               d.name AS department, s.risk_score,
               ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
               ROUND(AVG(mr.percentage)::numeric,1) AS avg_marks,
               CASE
                   WHEN s.risk_score >= :critical_risk THEN 'critical'
                   WHEN s.risk_score >= :risk_threshold THEN 'high'
                   ELSE 'medium'
               END AS risk_level
        FROM faculty_subject_assignments fsa
        JOIN marks_records mr ON mr.subject_id = fsa.subject_id
        JOIN students s ON s.id = mr.student_id AND s.status = 'active'
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE fsa.user_id = :uid AND s.risk_score >= :risk_threshold
        GROUP BY s.id, s.name, s.roll_number, s.current_semester, d.name, s.risk_score, att.attendance_pct
        ORDER BY s.risk_score DESC NULLS LAST
        LIMIT 15
    """), {"uid": user_id, "risk_threshold": risk_score_threshold, "critical_risk": risk_score_threshold + 20})
    risk_rows = r.fetchall()
    at_risk_students = [dict(zip(r.keys(), row)) for row in risk_rows]

    # 2. Students failing subjects taught by this faculty
    r = await db.execute(text("""
        SELECT DISTINCT s.id, s.name, s.roll_number, s.current_semester,
               d.name AS department, s.risk_score,
               ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
               ROUND(AVG(mr.percentage)::numeric,1) AS avg_marks,
               'high' AS risk_level
        FROM faculty_subject_assignments fsa
        JOIN marks_records mr ON mr.subject_id = fsa.subject_id
        JOIN students s ON s.id = mr.student_id AND s.status = 'active'
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE fsa.user_id = :uid AND mr.percentage < :pass_mark_threshold
        GROUP BY s.id, s.name, s.roll_number, s.current_semester, d.name, s.risk_score, att.attendance_pct
        ORDER BY avg_marks ASC NULLS LAST
        LIMIT 15
    """), {"uid": user_id, "pass_mark_threshold": pass_mark_threshold})
    fail_rows = r.fetchall()
    failed_subject_students = [dict(zip(r.keys(), row)) for row in fail_rows]

    # 3. Students with low attendance in subjects taught by this faculty
    r = await db.execute(text("""
        SELECT DISTINCT s.id, s.name, s.roll_number, s.current_semester,
               d.name AS department, s.risk_score,
               ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
               ROUND(AVG(mr.percentage)::numeric,1) AS avg_marks,
               'critical' AS risk_level
        FROM faculty_subject_assignments fsa
        JOIN marks_records mr ON mr.subject_id = fsa.subject_id
        JOIN students s ON s.id = mr.student_id AND s.status = 'active'
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE fsa.user_id = :uid AND att.attendance_pct < :attendance_threshold
        GROUP BY s.id, s.name, s.roll_number, s.current_semester, d.name, s.risk_score, att.attendance_pct
        ORDER BY attendance_pct ASC NULLS LAST
        LIMIT 15
    """), {"uid": user_id, "attendance_threshold": attendance_threshold})
    att_rows = r.fetchall()
    low_attendance_students = [dict(zip(r.keys(), row)) for row in att_rows]

    return {
        "faculty": fac_dict,
        "performance_trend": trend,
        "subjects": subjects,
        "at_risk_students": at_risk_students,
        "failed_subject_students": failed_subject_students,
        "low_attendance_students": low_attendance_students,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: HOD INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/hod")
async def list_hods(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """All HODs with their latest performance metrics."""
    r = await db.execute(text("""
        SELECT
            u.id, u.full_name, u.email, u.employee_id, u.designation,
            u.experience_years, u.qualification,
            d.id AS dept_id, d.name AS dept_name, d.code AS dept_code,
            hpm.dept_health_score,
            hpm.faculty_compliance_rate,
            hpm.student_risk_count,
            hpm.pass_rate AS hod_pass_rate,
            hpm.attendance_rate AS hod_att_rate,
            hpm.review_meetings_held,
            hpm.faculty_feedback_avg,
            hpm.month AS latest_month,
            -- Live faculty count in their dept
            (SELECT COUNT(*) FROM users u2 WHERE u2.department_id = d.id
             AND u2.role = 'faculty' AND u2.is_active = TRUE) AS faculty_count,
            -- Live student count
            (SELECT COUNT(*) FROM students s WHERE s.department_id = d.id
             AND s.status = 'active') AS student_count
        FROM users u
        JOIN departments d ON d.id = u.department_id
        LEFT JOIN LATERAL (
            SELECT * FROM hod_performance_metrics h2
            WHERE h2.user_id = u.id
            ORDER BY h2.month DESC
            LIMIT 1
        ) hpm ON TRUE
        WHERE u.role = 'hod' AND u.is_active = TRUE AND u.department_id IS NOT NULL
        ORDER BY hpm.dept_health_score DESC NULLS LAST
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    hods = []
    for row in rows:
        data = dict(zip(cols, row))
        score = float(data.get("dept_health_score") or 0)
        if score >= 85:
            grade, color = "Excellent", "green"
        elif score >= 70:
            grade, color = "Good", "blue"
        elif score >= 55:
            grade, color = "Needs Attention", "amber"
        elif score > 0:
            grade, color = "Critical", "red"
        else:
            grade, color = "No Data", "gray"
        data["hod_grade"] = grade
        data["hod_color"] = color
        hods.append(data)
    return hods


@router.get("/hod/rankings")
async def get_hod_rankings(
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """HOD performance ranking by department health score."""
    r = await db.execute(text("""
        SELECT
            u.id, u.full_name, u.employee_id,
            d.name AS dept_name, d.code AS dept_code,
            hpm.dept_health_score,
            hpm.faculty_compliance_rate,
            hpm.student_risk_count,
            hpm.pass_rate,
            hpm.attendance_rate,
            hpm.month AS latest_month
        FROM users u
        JOIN departments d ON d.id = u.department_id
        LEFT JOIN LATERAL (
            SELECT * FROM hod_performance_metrics h2
            WHERE h2.user_id = u.id
            ORDER BY h2.month DESC
            LIMIT 1
        ) hpm ON TRUE
        WHERE u.role = 'hod' AND u.is_active = TRUE AND u.department_id IS NOT NULL
          AND hpm.id IS NOT NULL
        ORDER BY hpm.dept_health_score DESC NULLS LAST
    """))
    rows = r.fetchall()
    cols = list(r.keys())
    all_hods = [dict(zip(cols, row)) for row in rows]
    ranked = []
    for i, hod in enumerate(all_hods):
        hod["rank"] = i + 1
        score = float(hod.get("dept_health_score") or 0)
        hod["grade"] = "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs Attention" if score >= 55 else "Critical"
        ranked.append(hod)
    return {"rankings": ranked, "total": len(ranked)}


@router.get("/hod/{user_id}")
async def get_hod_profile(
    user_id: int,
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Full HOD profile with 6-month trend, faculty compliance, and student risk data."""
    # HOD info
    r = await db.execute(text("""
        SELECT u.id, u.full_name, u.email, u.employee_id, u.designation,
               u.experience_years, u.qualification, u.phone, u.last_login,
               d.id AS dept_id, d.name AS dept_name, d.code AS dept_code
        FROM users u
        JOIN departments d ON d.id = u.department_id
        WHERE u.id = :uid AND u.role = 'hod' AND u.is_active = TRUE
    """), {"uid": user_id})
    hod = r.fetchone()
    if not hod:
        raise HTTPException(status_code=404, detail="HOD not found")
    hod_dict = dict(zip(r.keys(), hod))
    dept_id = hod_dict["dept_id"]

    # 6-month HOD performance trend
    r = await db.execute(text("""
        SELECT month, dept_health_score, faculty_compliance_rate,
               student_risk_count, pass_rate, attendance_rate,
               review_meetings_held, faculty_feedback_avg
        FROM hod_performance_metrics
        WHERE user_id = :uid
        ORDER BY month ASC
        LIMIT 6
    """), {"uid": user_id})
    trend_rows = r.fetchall()
    trend = [dict(zip(r.keys(), row)) for row in trend_rows]

    # Faculty in this department with their compliance
    r = await db.execute(text("""
        SELECT
            u2.id, u2.full_name, u2.employee_id, u2.designation,
            spm.attendance_submission_pct,
            spm.marks_submission_pct,
            spm.student_pass_rate,
            spm.feedback_score,
            spm.month AS latest_month
        FROM users u2
        LEFT JOIN LATERAL (
            SELECT * FROM staff_performance_metrics s2
            WHERE s2.user_id = u2.id
            ORDER BY s2.month DESC
            LIMIT 1
        ) spm ON TRUE
        WHERE u2.department_id = :dept_id AND u2.role = 'faculty' AND u2.is_active = TRUE
        ORDER BY spm.student_pass_rate DESC NULLS LAST
    """), {"dept_id": dept_id})
    fac_rows = r.fetchall()
    faculty_compliance = []
    for row in fac_rows:
        fac_data = dict(zip(r.keys(), row))
        att_sub = float(fac_data.get("attendance_submission_pct") or 0)
        marks_sub = float(fac_data.get("marks_submission_pct") or 0)
        fac_data["compliance_score"] = round((att_sub + marks_sub) / 2, 1) if (att_sub or marks_sub) else None
        fac_data["is_compliant"] = (att_sub >= 80 and marks_sub >= 80)
        faculty_compliance.append(fac_data)

    # At-risk students in dept
    r = await db.execute(text("""
        SELECT s.id, s.name, s.roll_number, s.current_semester, s.risk_score,
               ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
               CASE
                   WHEN s.risk_score >= 80 THEN 'critical'
                   WHEN s.risk_score >= 60 THEN 'high'
                   ELSE 'medium'
               END AS risk_level
        FROM students s
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        WHERE s.department_id = :dept_id AND s.status = 'active' AND s.risk_score >= 60
        ORDER BY s.risk_score DESC
        LIMIT 10
    """), {"dept_id": dept_id})
    risk_rows = r.fetchall()
    at_risk_students = [dict(zip(r.keys(), row)) for row in risk_rows]

    # Department live KPIs
    r = await db.execute(text("""
        SELECT
            COUNT(DISTINCT s.id) AS total_students,
            ROUND(AVG(att.attendance_pct)::numeric,1) AS avg_attendance,
            ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*),0))::numeric,1) AS pass_rate,
            COUNT(DISTINCT s.id) FILTER (WHERE s.risk_score >= 60) AS at_risk
        FROM students s
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
        WHERE s.department_id = :dept_id AND s.status = 'active'
    """), {"dept_id": dept_id})
    kpi_row = r.fetchone()
    dept_kpis = {
        "total_students": kpi_row[0] or 0,
        "avg_attendance": float(kpi_row[1] or 0),
        "pass_rate": float(kpi_row[2] or 0),
        "at_risk_count": kpi_row[3] or 0,
    }

    return {
        "hod": hod_dict,
        "performance_trend": trend,
        "faculty_compliance": faculty_compliance,
        "at_risk_students": at_risk_students,
        "dept_kpis": dept_kpis,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: Underperforming Students by Department/Staff
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/departments/{dept_id}/underperforming")
async def get_underperforming_students(
    dept_id: int,
    current_user: User = Depends(get_principal),
    db: AsyncSession = Depends(get_db)
):
    """Students underperforming in a department, grouped by their subject staff."""
    r = await db.execute(text("""
        SELECT
            u.id AS faculty_id, u.full_name AS faculty_name, u.employee_id,
            sub.id AS subject_id, sub.name AS subject_name, sub.code AS subject_code,
            sub.semester_number,
            s.id AS student_id, s.name AS student_name, s.roll_number, s.current_semester,
            s.risk_score,
            ROUND(att.attendance_pct::numeric,1) AS attendance_pct,
            mr.percentage AS marks_pct
        FROM faculty_subject_assignments fsa
        JOIN users u ON u.id = fsa.user_id
        JOIN subjects sub ON sub.id = fsa.subject_id AND sub.department_id = :dept_id
        JOIN marks_records mr ON mr.subject_id = sub.id AND mr.percentage < 50 AND mr.is_absent = FALSE
        JOIN students s ON s.id = mr.student_id AND s.status = 'active'
        LEFT JOIN (
            SELECT student_id, AVG(attendance_pct) AS attendance_pct
            FROM attendance_summary GROUP BY student_id
        ) att ON att.student_id = s.id
        ORDER BY u.full_name, sub.name, s.risk_score DESC NULLS LAST
        LIMIT 50
    """), {"dept_id": dept_id})
    rows = r.fetchall()
    cols = list(r.keys())
    raw = [dict(zip(cols, row)) for row in rows]

    # Group by faculty
    faculty_map: dict = {}
    for item in raw:
        fid = item["faculty_id"]
        if fid not in faculty_map:
            faculty_map[fid] = {
                "faculty_id": fid,
                "faculty_name": item["faculty_name"],
                "employee_id": item["employee_id"],
                "subjects": {}
            }
        sid = item["subject_id"]
        if sid not in faculty_map[fid]["subjects"]:
            faculty_map[fid]["subjects"][sid] = {
                "subject_id": sid,
                "subject_name": item["subject_name"],
                "subject_code": item["subject_code"],
                "semester": item["semester_number"],
                "students": []
            }
        faculty_map[fid]["subjects"][sid]["students"].append({
            "student_id": item["student_id"],
            "name": item["student_name"],
            "roll_number": item["roll_number"],
            "semester": item["current_semester"],
            "risk_score": float(item["risk_score"] or 0),
            "attendance_pct": float(item["attendance_pct"] or 0),
            "marks_pct": float(item["marks_pct"] or 0),
        })

    result = []
    for fac in faculty_map.values():
        fac["subjects"] = list(fac["subjects"].values())
        fac["total_underperforming"] = sum(len(s["students"]) for s in fac["subjects"])
        result.append(fac)
    result.sort(key=lambda x: x["total_underperforming"], reverse=True)
    return {"faculty_groups": result, "dept_id": dept_id}
