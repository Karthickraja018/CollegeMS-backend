"""
Department Intelligence API — Per-department analytics and insights.

Row-level access:
- Admin/Principal: any department
- HOD: only their own department
- Faculty: read-only access to their department (limited)

Endpoints:
  GET /api/department-intelligence/                    — list all depts (scoped)
  GET /api/department-intelligence/{id}/overview       — KPIs + AHS
  GET /api/department-intelligence/{id}/subject-analysis
  GET /api/department-intelligence/{id}/faculty-performance
  GET /api/department-intelligence/{id}/student-trends
  GET /api/department-intelligence/{id}/risk-distribution
  GET /api/department-intelligence/compare             — multi-dept (Principal/Admin)
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, get_data_scope
from app.access_policies import assert_department_access
from app.models.user import User, UserRole
from app.roles import DataScope
from app.utils.academic_metrics import compute_ahs

router = APIRouter(prefix="/department-intelligence", tags=["department-intelligence"])


async def _get_dept_ahs(db: AsyncSession, dept_id: int) -> dict:
    """Compute Academic Health Score for a department."""
    # Fetch dynamic thresholds
    s_res = await db.execute(text(
        "SELECT c.settings FROM colleges c JOIN departments d ON d.college_id = c.id WHERE d.id = :dept_id"
    ), {"dept_id": dept_id})
    settings = s_res.scalar() or {}
    pass_threshold = float(settings.get("pass_mark_threshold", 50))
    risk_threshold = float(settings.get("risk_score_threshold", 60))

    r = await db.execute(
        text("""
            SELECT
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_att,
                ROUND((COUNT(*) FILTER (WHERE mr.percentage >= :pass_threshold) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
                COUNT(*) FILTER (WHERE s.risk_score >= :risk_threshold) AS at_risk,
                COUNT(*) AS total_students,
                ROUND(AVG(mr.percentage)::numeric, 1) AS avg_marks
            FROM students s
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) AS attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
            WHERE s.department_id = :dept_id AND s.status = 'active'
        """),
        {"dept_id": dept_id, "pass_threshold": pass_threshold, "risk_threshold": risk_threshold},
    )
    row = r.fetchone()
    if not row:
        return {"score": 0, "grade": "No Data", "color": "gray"}

    avg_att = float(row[0] or 0)
    pass_rate = float(row[1] or 0)
    at_risk = row[2] or 0
    total = row[3] or 1
    avg_marks = float(row[4] or 0)
    risk_ratio = at_risk / total

    return compute_ahs(avg_att, pass_rate, risk_ratio, avg_marks)


@router.get("/")
async def list_departments(
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """Return departments accessible to the user."""
    if scope.is_institution_wide:
        r = await db.execute(
            text("SELECT id, name, code FROM departments WHERE is_active = TRUE ORDER BY name")
        )
    else:
        r = await db.execute(
            text("SELECT id, name, code FROM departments WHERE id = :dept_id AND is_active = TRUE"),
            {"dept_id": scope.department_id},
        )
    rows = r.fetchall()
    cols = list(r.keys())
    return [dict(zip(cols, row)) for row in rows]


@router.get("/{dept_id}/overview")
async def get_department_overview(
    dept_id: int,
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """Department KPIs + Academic Health Score."""
    assert_department_access(current_user, dept_id)

    # Dept info
    r = await db.execute(
        text("SELECT id, name, code FROM departments WHERE id = :dept_id"),
        {"dept_id": dept_id},
    )
    dept = r.fetchone()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    # Aggregate KPIs
    r = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT s.id) AS total_students,
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_att,
                ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
                COUNT(*) FILTER (WHERE s.risk_score >= 60) AS at_risk,
                COUNT(*) FILTER (WHERE s.risk_score >= 80) AS critical_risk
            FROM students s
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) AS attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
            WHERE s.department_id = :dept_id AND s.status = 'active'
        """),
        {"dept_id": dept_id},
    )
    agg = r.fetchone()

    # Faculty count
    r = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE department_id = :dept_id AND role IN ('faculty', 'hod') AND is_active = TRUE"),
        {"dept_id": dept_id},
    )
    faculty_count = r.scalar() or 0

    # Subject count
    r = await db.execute(
        text("SELECT COUNT(*) FROM subjects WHERE department_id = :dept_id AND is_active = TRUE"),
        {"dept_id": dept_id},
    )
    subject_count = r.scalar() or 0

    ahs = await _get_dept_ahs(db, dept_id)

    return {
        "department": {"id": dept[0], "name": dept[1], "code": dept[2]},
        "kpis": {
            "total_students": agg[0] or 0,
            "avg_attendance": float(agg[1] or 0),
            "pass_rate": float(agg[2] or 0),
            "at_risk_students": agg[3] or 0,
            "critical_risk_students": agg[4] or 0,
            "faculty_count": faculty_count,
            "subject_count": subject_count,
        },
        "academic_health": ahs,
    }


@router.get("/{dept_id}/subject-analysis")
async def get_subject_analysis(
    dept_id: int,
    semester: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subject-wise pass rates and average marks for a department."""
    assert_department_access(current_user, dept_id)

    sem_clause = "AND sub.semester_number = :semester" if semester else ""
    params = {"dept_id": dept_id}
    if semester:
        params["semester"] = semester

    r = await db.execute(
        text(f"""
            SELECT
                sub.id, sub.name, sub.code, sub.semester_number,
                COUNT(DISTINCT mr.student_id) AS total_students,
                COUNT(*) FILTER (WHERE mr.percentage >= 50) AS passed,
                ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
                ROUND(AVG(mr.percentage)::numeric, 1) AS avg_marks,
                MIN(mr.percentage) AS min_marks,
                MAX(mr.percentage) AS max_marks
            FROM subjects sub
            LEFT JOIN marks_records mr ON mr.subject_id = sub.id AND mr.is_absent = FALSE
            WHERE sub.department_id = :dept_id AND sub.is_active = TRUE {sem_clause}
            GROUP BY sub.id, sub.name, sub.code, sub.semester_number
            ORDER BY sub.semester_number, pass_rate ASC NULLS LAST
        """),
        params,
    )
    rows = r.fetchall()
    cols = list(r.keys())
    subjects = [dict(zip(cols, row)) for row in rows]

    # Add risk flag
    for s in subjects:
        rate = float(s.get("pass_rate") or 0)
        s["risk_flag"] = "critical" if rate < 40 else "warning" if rate < 60 else "good"

    return {"subjects": subjects, "department_id": dept_id}


@router.get("/{dept_id}/faculty-performance")
async def get_faculty_performance(
    dept_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """Faculty-wise student outcomes for a department."""
    assert_department_access(current_user, dept_id)

    r = await db.execute(
        text("""
            SELECT
                u.id AS faculty_id, u.full_name AS faculty_name,
                u.research_output_score, u.feedback_score,
                COUNT(DISTINCT fsa.subject_id) AS subjects_assigned,
                COUNT(DISTINCT mr.student_id) AS students_taught,
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_student_att,
                ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
                spm.attendance_submission_pct,
                spm.marks_submission_pct
            FROM users u
            JOIN faculty_subject_assignments fsa ON fsa.user_id = u.id
            LEFT JOIN marks_records mr ON mr.subject_id = fsa.subject_id AND mr.is_absent = FALSE
            LEFT JOIN students s ON s.id = mr.student_id AND s.status = 'active'
            LEFT JOIN LATERAL (
                SELECT attendance_submission_pct, marks_submission_pct 
                FROM staff_performance_metrics s2
                WHERE s2.user_id = u.id
                ORDER BY s2.month DESC
                LIMIT 1
            ) spm ON TRUE
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) AS attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            WHERE u.department_id = :dept_id AND u.role IN ('faculty', 'hod') AND u.is_active = TRUE
            GROUP BY u.id, u.full_name, u.research_output_score, u.feedback_score, spm.attendance_submission_pct, spm.marks_submission_pct
            ORDER BY pass_rate DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        {"dept_id": dept_id, "limit": limit, "offset": offset},
    )
    rows = r.fetchall()
    cols = list(r.keys())
    faculty_list = [dict(zip(cols, row)) for row in rows]
    
    for f in faculty_list:
        att_sub = float(f.get("attendance_submission_pct") or 0)
        marks_sub = float(f.get("marks_submission_pct") or 0)
        f["compliance_score"] = round((att_sub + marks_sub) / 2, 1) if (att_sub or marks_sub) else None
        
    return {"faculty": faculty_list}


@router.get("/{dept_id}/student-trends")
async def get_student_trends(
    dept_id: int,
    months: int = Query(6, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Monthly attendance and marks trend for the department."""
    assert_department_access(current_user, dept_id)

    r = await db.execute(
        text("""
            SELECT
                TO_CHAR(a.date, 'Mon YY') AS month,
                DATE_TRUNC('month', a.date) AS month_order,
                ROUND(COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0), 1) AS attendance
            FROM attendance a
            JOIN students s ON s.id = a.student_id AND s.status = 'active' AND s.department_id = :dept_id
            WHERE a.date >= NOW() - (:months * INTERVAL '1 month')
            GROUP BY TO_CHAR(a.date, 'Mon YY'), DATE_TRUNC('month', a.date)
            ORDER BY month_order
        """),
        {"dept_id": dept_id, "months": months},
    )
    rows = r.fetchall()
    return {"trends": [{"month": r[0], "attendance": float(r[2] or 0)} for r in rows]}


@router.get("/{dept_id}/risk-distribution")
async def get_risk_distribution(
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Risk score distribution histogram for a department."""
    assert_department_access(current_user, dept_id)

    r = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE risk_score < 20) AS "0-20",
                COUNT(*) FILTER (WHERE risk_score >= 20 AND risk_score < 40) AS "20-40",
                COUNT(*) FILTER (WHERE risk_score >= 40 AND risk_score < 60) AS "40-60",
                COUNT(*) FILTER (WHERE risk_score >= 60 AND risk_score < 80) AS "60-80",
                COUNT(*) FILTER (WHERE risk_score >= 80) AS "80-100"
            FROM students
            WHERE department_id = :dept_id AND status = 'active'
        """),
        {"dept_id": dept_id},
    )
    row = r.fetchone()
    if not row:
        return {"distribution": []}

    cols = list(r.keys())
    distribution = [
        {"range": cols[i], "count": row[i] or 0,
         "level": "low" if i == 0 else "low" if i == 1 else "medium" if i == 2 else "high" if i == 3 else "critical"}
        for i in range(len(cols))
    ]
    return {"distribution": distribution, "department_id": dept_id}


@router.get("/compare")
async def compare_departments(
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """
    Multi-department comparison table.
    Only available to Admin and Principal.
    """
    if not scope.is_institution_wide:
        raise HTTPException(
            status_code=403,
            detail="Department comparison is only available to Principal and Admin."
        )

    r = await db.execute(
        text("""
            SELECT
                d.id, d.name, d.code,
                COUNT(DISTINCT s.id) AS students,
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_att,
                ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) AS pass_rate,
                COUNT(*) FILTER (WHERE s.risk_score >= 60) AS at_risk,
                COUNT(DISTINCT u.id) AS faculty_count,
                ROUND(AVG(mr.percentage)::numeric, 1) AS avg_marks
            FROM departments d
            LEFT JOIN students s ON s.department_id = d.id AND s.status = 'active'
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) AS attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            LEFT JOIN marks_records mr ON mr.student_id = s.id AND mr.is_absent = FALSE
            LEFT JOIN users u ON u.department_id = d.id AND u.role IN ('faculty', 'hod') AND u.is_active = TRUE
            WHERE d.is_active = TRUE
            GROUP BY d.id, d.name, d.code
            ORDER BY d.name
        """),
    )
    rows = r.fetchall()
    cols = list(r.keys())
    depts = [dict(zip(cols, row)) for row in rows]

    # Add AHS for each dept
    for dept in depts:
        total = dept["students"] or 1
        risk_ratio = (dept["at_risk"] or 0) / total
        att = float(dept["avg_att"] or 0)
        pass_r = float(dept["pass_rate"] or 0)
        avg_marks = float(dept["avg_marks"] or 0)
        dept["ahs"] = compute_ahs(att, pass_r, risk_ratio, avg_marks)["score"]

    return {"departments": depts}


@router.get("/{dept_id}/faculty/{faculty_id}/profile")
async def get_faculty_profile(
    dept_id: int,
    faculty_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deep profile for a specific faculty member including subject analytics, recent classes, and AI advice."""
    assert_department_access(current_user, dept_id)

    # 1. Faculty Details
    r = await db.execute(
        text("""
            SELECT u.id, u.full_name, u.employee_id, u.role, u.designation,
                   d.name as dept_name,
                   spm.attendance_submission_pct,
                   spm.marks_submission_pct
            FROM users u
            JOIN departments d ON d.id = u.department_id
            LEFT JOIN LATERAL (
                SELECT attendance_submission_pct, marks_submission_pct 
                FROM staff_performance_metrics s2
                WHERE s2.user_id = u.id
                ORDER BY s2.month DESC
                LIMIT 1
            ) spm ON TRUE
            WHERE u.id = :faculty_id AND u.department_id = :dept_id
        """),
        {"faculty_id": faculty_id, "dept_id": dept_id}
    )
    faculty_row = r.fetchone()
    if not faculty_row:
        raise HTTPException(status_code=404, detail="Faculty not found in this department")
    
    att_sub = float(faculty.get("attendance_submission_pct") or 0)
    marks_sub = float(faculty.get("marks_submission_pct") or 0)
    faculty["compliance_score"] = round((att_sub + marks_sub) / 2, 1) if (att_sub or marks_sub) else None

    # 2. Subject Performance (Marks and pass rate for subjects taught by this faculty)
    r = await db.execute(
        text("""
            SELECT sub.id, sub.name, sub.code,
                   COUNT(DISTINCT mr.student_id) as total_students,
                   COUNT(*) FILTER (WHERE mr.percentage >= 50) as passed_students,
                   ROUND((COUNT(*) FILTER (WHERE mr.percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) as pass_rate,
                   ROUND(AVG(mr.percentage)::numeric, 1) as avg_marks
            FROM faculty_subject_assignments fsa
            JOIN subjects sub ON fsa.subject_id = sub.id
            LEFT JOIN marks_records mr ON mr.subject_id = sub.id AND mr.is_absent = FALSE
            WHERE fsa.user_id = :faculty_id
            GROUP BY sub.id, sub.name, sub.code
            ORDER BY pass_rate ASC NULLS LAST
        """),
        {"faculty_id": faculty_id}
    )
    subjects = [dict(zip(r.keys(), row)) for row in r.fetchall()]
    
    # 3. Overall Student Attendance (across all subjects taught by this faculty)
    r = await db.execute(
        text("""
            SELECT
                ROUND((COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) as avg_student_att
            FROM attendance_records a
            JOIN faculty_subject_assignments fsa ON fsa.subject_id = a.subject_id
            WHERE fsa.user_id = :faculty_id
        """),
        {"faculty_id": faculty_id}
    )
    att_row = r.fetchone()
    avg_student_att = float(att_row[0] or 0) if att_row else 0

    # 4. Recent Classes (last 10 classes marked by this faculty)
    r = await db.execute(
        text("""
            SELECT a.date, a.period, sub.name as subject_name,
                   COUNT(*) as total_students,
                   COUNT(*) FILTER (WHERE a.status = 'present') as present,
                   ROUND((COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1) as att_pct
            FROM attendance_records a
            JOIN subjects sub ON a.subject_id = sub.id
            WHERE a.marked_by = :faculty_id
            GROUP BY a.date, a.period, sub.name
            ORDER BY a.date DESC, a.period DESC
            LIMIT 10
        """),
        {"faculty_id": faculty_id}
    )
    recent_classes = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # 5. Poor Performing Students
    r = await db.execute(
        text("""
            SELECT DISTINCT s.id, s.name, s.roll_number,
                   ROUND(AVG(mr.percentage)::numeric, 1) as marks,
                   ROUND(AVG(att.attendance_pct)::numeric, 1) as attendance
            FROM students s
            JOIN marks_records mr ON mr.student_id = s.id
            JOIN faculty_subject_assignments fsa ON fsa.subject_id = mr.subject_id
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) as attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            WHERE fsa.user_id = :faculty_id AND s.status = 'active'
                  AND (mr.percentage < 50 OR att.attendance_pct < 65)
            GROUP BY s.id, s.name, s.roll_number
            ORDER BY marks ASC NULLS LAST
            LIMIT 10
        """),
        {"faculty_id": faculty_id}
    )
    poor_students = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # 6. AI Recommendations (heuristic based for now)
    recs = []
    compliance = faculty.get("compliance_score") or 0
    if compliance < 75:
        recs.append({
            "priority": "high",
            "action": "Address Low Compliance",
            "detail": f"Faculty compliance score is critically low ({compliance}%). Review timely attendance and marks submission."
        })
    
    for sub in subjects:
        pr = float(sub.get("pass_rate") or 0)
        if pr < 60 and sub.get("total_students", 0) > 0:
            recs.append({
                "priority": "critical" if pr < 50 else "high",
                "action": f"Review Performance in {sub['name']}",
                "detail": f"Pass rate is only {pr}% in {sub['code']}. Recommend organizing extra tutorials or peer-reviewing teaching methods."
            })
    
    if not recs:
        recs.append({
            "priority": "low",
            "action": "Maintain Current Performance",
            "detail": f"{faculty['full_name']} is performing well with high pass rates and compliance."
        })

    return {
        "faculty": faculty,
        "kpis": {
            "avg_student_attendance": avg_student_att,
            "total_subjects": len(subjects),
            "compliance": compliance
        },
        "subjects": subjects,
        "recent_classes": [
            {**c, "date": str(c["date"])} for c in recent_classes
        ],
        "poor_students": poor_students,
        "recommendations": recs
    }
