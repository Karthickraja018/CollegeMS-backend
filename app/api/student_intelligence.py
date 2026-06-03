"""
Student Intelligence API — Risk profiles, trends, and AI recommendations.

All endpoints enforce row-level access control:
- Admin/Principal: any student
- HOD: students in their department
- Faculty: students in their assigned subjects

Endpoints:
  GET /api/student-intelligence/at-risk          — paginated at-risk list
  GET /api/student-intelligence/{id}/profile     — full risk profile
  GET /api/student-intelligence/{id}/attendance-trend
  GET /api/student-intelligence/{id}/marks-trend
  GET /api/student-intelligence/{id}/recommendations
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, get_data_scope
from app.access_policies import assert_student_access, get_department_filter_sql, get_student_id_filter_sql
from app.models.user import User
from app.roles import DataScope

router = APIRouter(prefix="/student-intelligence", tags=["student-intelligence"])


@router.get("/at-risk")
async def get_at_risk_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    department_id: int | None = None,
    risk_level: str | None = Query(None, description="critical|high|medium"),
    semester: int | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """
    Return paginated list of at-risk students scoped to user's role.
    HOD: only own dept. Faculty: only assigned students.
    """
    dept_clause, dept_params = get_department_filter_sql(current_user)
    student_clause, student_params = await get_student_id_filter_sql(current_user, db)
    params = {**dept_params, **student_params}

    # Additional filters from query params
    extra_clauses = []
    if department_id and scope.is_institution_wide:
        extra_clauses.append("AND s.department_id = :filter_dept_id")
        params["filter_dept_id"] = department_id

    if semester:
        extra_clauses.append("AND s.current_semester = :semester")
        params["semester"] = semester

    if search:
        extra_clauses.append("AND (s.name ILIKE :search OR s.roll_number ILIKE :search)")
        params["search"] = f"%{search}%"

    risk_clause = ""
    if risk_level == "critical":
        risk_clause = "AND s.risk_score >= 80"
    elif risk_level == "high":
        risk_clause = "AND s.risk_score >= 60 AND s.risk_score < 80"
    elif risk_level == "medium":
        risk_clause = "AND s.risk_score >= 40 AND s.risk_score < 60"
    elif risk_level == "low":
        risk_clause = "AND s.risk_score < 40"

    extra_sql = " ".join(extra_clauses)

    base_query = f"""
        FROM students s
        JOIN departments d ON d.id = s.department_id
        LEFT JOIN (
            SELECT student_id, ROUND(AVG(attendance_pct)::numeric, 1) AS attendance_pct
            FROM attendance_summary
            GROUP BY student_id
        ) att ON att.student_id = s.id
        LEFT JOIN (
            SELECT student_id, ROUND(AVG(percentage)::numeric, 1) AS avg_marks
            FROM marks_records WHERE is_absent = FALSE
            GROUP BY student_id
        ) m ON m.student_id = s.id
        WHERE s.status = 'active'
        {risk_clause}
        {dept_clause}
        {student_clause}
        {extra_sql}
    """

    # Count
    count_r = await db.execute(text(f"SELECT COUNT(*) {base_query}"), params)
    total = count_r.scalar() or 0

    # Paginated results
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    r = await db.execute(
        text(f"""
            SELECT
                s.id, s.roll_number, s.name, s.current_semester, s.batch, s.section,
                s.risk_score,
                d.name AS department, d.code AS dept_code,
                ROUND(att.attendance_pct::numeric, 1) AS attendance_pct,
                m.avg_marks,
                CASE
                    WHEN s.risk_score >= 80 THEN 'critical'
                    WHEN s.risk_score >= 60 THEN 'high'
                    WHEN s.risk_score >= 40 THEN 'medium'
                    ELSE 'low'
                END AS risk_level
            {base_query}
            ORDER BY s.risk_score DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = r.fetchall()
    cols = list(r.keys())
    students = [dict(zip(cols, row)) for row in rows]

    return {
        "data": students,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "scope": scope.role,
    }


@router.get("/{student_id}/profile")
async def get_student_profile(
    student_id: int,
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    db: AsyncSession = Depends(get_db),
):
    """Full risk profile for a student with attendance, marks, and risk analysis."""
    await assert_student_access(current_user, student_id, db)

    # Core student info
    r = await db.execute(
        text("""
            SELECT s.*, d.name AS dept_name, d.code AS dept_code,
                p.name AS program_name
            FROM students s
            JOIN departments d ON d.id = s.department_id
            LEFT JOIN programs p ON p.id = s.program_id
            WHERE s.id = :sid
        """),
        {"sid": student_id},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")

    cols = list(r.keys())
    student = dict(zip(cols, row))

    # Attendance summary
    r = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_classes,
                COUNT(*) FILTER (WHERE a.status = 'present') AS present,
                COUNT(*) FILTER (WHERE a.status = 'absent') AS absent,
                ROUND(COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0), 1) AS pct
            FROM attendance_records a
            WHERE a.student_id = :sid
        """),
        {"sid": student_id},
    )
    att_row = r.fetchone()

    # Subject-wise attendance
    r = await db.execute(
        text("""
            SELECT sub.name, sub.code,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE a.status = 'present') AS present,
                ROUND(COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0), 1) AS pct
            FROM attendance_records a
            JOIN subjects sub ON sub.id = a.subject_id
            WHERE a.student_id = :sid
            GROUP BY sub.name, sub.code
            ORDER BY pct ASC
        """),
        {"sid": student_id},
    )
    subj_att = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Marks summary by subject
    r = await db.execute(
        text("""
            SELECT sub.name, sub.code, mr.exam_type,
                mr.marks_obtained, mr.max_marks, mr.percentage,
                mr.is_absent, mr.is_withheld
            FROM marks_records mr
            JOIN subjects sub ON sub.id = mr.subject_id
            WHERE mr.student_id = :sid
            ORDER BY sub.name, mr.exam_type
        """),
        {"sid": student_id},
    )
    marks = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Risk breakdown
    risk_score = float(student.get("risk_score") or 0)
    att_pct = float(att_row[3]) if att_row and att_row[3] else 0
    avg_marks = sum(float(m.get("percentage") or 0) for m in marks if not m["is_absent"]) / max(1, len([m for m in marks if not m["is_absent"]]))

    risk_factors = []
    if att_pct < 75:
        risk_factors.append({
            "factor": "Low Attendance",
            "value": f"{att_pct}%",
            "threshold": "75%",
            "severity": "critical" if att_pct < 60 else "high",
        })
    if avg_marks < 50:
        risk_factors.append({
            "factor": "Below Average Marks",
            "value": f"{round(avg_marks, 1)}%",
            "threshold": "50%",
            "severity": "critical" if avg_marks < 35 else "high",
        })
    for sa in subj_att:
        if sa["pct"] and float(sa["pct"]) < 60:
            risk_factors.append({
                "factor": f"Very Low Attendance in {sa['name']}",
                "value": f"{sa['pct']}%",
                "threshold": "60%",
                "severity": "critical",
            })

    return {
        "student": student,
        "attendance": {
            "total_classes": att_row[0] if att_row else 0,
            "present": att_row[1] if att_row else 0,
            "absent": att_row[2] if att_row else 0,
            "percentage": att_pct,
            "by_subject": subj_att,
        },
        "marks": marks,
        "risk": {
            "score": risk_score,
            "level": (
                "critical" if risk_score >= 80
                else "high" if risk_score >= 60
                else "medium" if risk_score >= 40
                else "low"
            ),
            "factors": risk_factors,
            "predictions": {
                "dropout_probability": round(min(risk_score * 0.85, 99.0), 1),
                "failure_probability": round(min(risk_score * 0.75 + (50 - min(avg_marks, 50)), 99.0), 1),
                "arrear_probability": round(min(risk_score * 0.6 + (100 - min(att_pct, 100)), 99.0), 1)
            }
        },
    }


@router.get("/{student_id}/attendance-trend")
async def get_student_attendance_trend(
    student_id: int,
    months: int = Query(6, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Monthly attendance trend for a student."""
    await assert_student_access(current_user, student_id, db)

    r = await db.execute(
        text("""
            SELECT
                TO_CHAR(a.date, 'Mon YYYY') AS month,
                DATE_TRUNC('month', a.date) AS month_order,
                COUNT(*) FILTER (WHERE a.status = 'present') AS present,
                COUNT(*) AS total,
                ROUND(COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0), 1) AS pct
            FROM attendance_records a
            WHERE a.student_id = :sid
            AND a.date >= NOW() - (:months * INTERVAL '1 month')
            GROUP BY TO_CHAR(a.date, 'Mon YYYY'), DATE_TRUNC('month', a.date)
            ORDER BY month_order
        """),
        {"sid": student_id, "months": months},
    )
    rows = r.fetchall()
    return [{"month": r[0], "present": r[2], "total": r[3], "attendance": float(r[4] or 0)} for r in rows]


@router.get("/{student_id}/marks-trend")
async def get_student_marks_trend(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subject-wise marks trend across exam types."""
    await assert_student_access(current_user, student_id, db)

    r = await db.execute(
        text("""
            SELECT sub.name AS subject, sub.code, mr.exam_type,
                mr.percentage, mr.marks_obtained, mr.max_marks
            FROM marks_records mr
            JOIN subjects sub ON sub.id = mr.subject_id
            WHERE mr.student_id = :sid AND mr.is_absent = FALSE
            ORDER BY sub.name, mr.exam_type
        """),
        {"sid": student_id},
    )
    rows = r.fetchall()
    cols = list(r.keys())
    return [dict(zip(cols, row)) for row in rows]


@router.get("/{student_id}/recommendations")
async def get_student_recommendations(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-generated intervention recommendations for a student."""
    await assert_student_access(current_user, student_id, db)

    # Get student risk data
    r = await db.execute(
        text("""
            SELECT s.name, s.risk_score,
                ROUND(att.attendance_pct::numeric, 1) AS att_pct,
                ROUND(m.avg_marks::numeric, 1) AS avg_marks
            FROM students s
            LEFT JOIN (
                SELECT student_id, AVG(attendance_pct) AS attendance_pct
                FROM attendance_summary
                GROUP BY student_id
            ) att ON att.student_id = s.id
            LEFT JOIN (
                SELECT student_id, AVG(percentage) AS avg_marks
                FROM marks_records WHERE is_absent = FALSE
                GROUP BY student_id
            ) m ON m.student_id = s.id
            WHERE s.id = :sid
        """),
        {"sid": student_id},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")

    name, risk, att_pct, avg_marks = row
    risk = float(risk or 0)
    att_pct = float(att_pct or 0)
    avg_marks = float(avg_marks or 0)

    recs = []

    if att_pct < 75:
        recs.append({
            "type": "attendance",
            "priority": "high",
            "action": f"Schedule attendance counseling for {name}",
            "detail": f"Current attendance at {att_pct}%. Student needs {max(0, round(75 - att_pct, 1))}% more classes to meet threshold.",
            "expected_impact": "Bring attendance above 75% within 3 weeks",
            "owner": "Faculty / HOD",
        })

    if avg_marks < 50:
        recs.append({
            "type": "academic",
            "priority": "high",
            "action": "Enroll in supplementary tutoring sessions",
            "detail": f"Average marks at {avg_marks}%. Identify weak subjects and provide targeted support.",
            "expected_impact": "+10-15 marks improvement in next exam cycle",
            "owner": "Subject Faculty",
        })

    if risk >= 80:
        recs.append({
            "type": "intervention",
            "priority": "critical",
            "action": "Initiate formal academic intervention",
            "detail": "Student is at critical risk. Notify parents/guardians and assign a faculty mentor.",
            "expected_impact": "Reduce dropout probability by 60% with structured intervention",
            "owner": "HOD + Principal",
        })

    if not recs:
        recs.append({
            "type": "monitoring",
            "priority": "low",
            "action": "Continue regular monitoring",
            "detail": f"{name} is performing within acceptable ranges. Maintain current tracking.",
            "expected_impact": "Sustain current performance trajectory",
            "owner": "Class Faculty",
        })

    return {"student_name": name, "risk_score": risk, "recommendations": recs}

from pydantic import BaseModel

class InterventionCreate(BaseModel):
    action_type: str
    notes: str | None = None

@router.get("/{student_id}/interventions")
async def list_student_interventions(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List interventions for a student."""
    await assert_student_access(current_user, student_id, db)
    
    r = await db.execute(
        text("""
            SELECT i.id, i.action_type, i.status, i.notes, i.created_at, u.full_name as owner_name
            FROM student_interventions i
            LEFT JOIN users u ON u.id = i.owner_id
            WHERE i.student_id = :sid
            ORDER BY i.created_at DESC
        """),
        {"sid": student_id}
    )
    rows = r.fetchall()
    return {"interventions": [dict(zip(r.keys(), row)) for row in rows]}

@router.post("/{student_id}/interventions")
async def create_student_intervention(
    student_id: int,
    intervention: InterventionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new intervention record for a student."""
    await assert_student_access(current_user, student_id, db)
    
    await db.execute(
        text("""
            INSERT INTO student_interventions (student_id, action_type, owner_id, status, notes)
            VALUES (:student_id, :action_type, :owner_id, 'active', :notes)
        """),
        {
            "student_id": student_id,
            "action_type": intervention.action_type,
            "owner_id": current_user.id,
            "notes": intervention.notes
        }
    )
    return {"status": "success"}


@router.get("/{student_id}/weekly-attendance")
async def get_student_weekly_attendance(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Last 7 days attendance, day by day and subject by subject."""
    await assert_student_access(current_user, student_id, db)

    # Day-by-day for last 7 days
    r = await db.execute(
        text("""
            SELECT
                a.date,
                TO_CHAR(a.date, 'Dy') AS day_name,
                COUNT(*) AS total_classes,
                COUNT(*) FILTER (WHERE a.status = 'present') AS present,
                COUNT(*) FILTER (WHERE a.status = 'absent') AS absent
            FROM attendance_records a
            WHERE a.student_id = :sid
            AND a.date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY a.date
            ORDER BY a.date
        """),
        {"sid": student_id},
    )
    daily = [
        {
            "date": str(row[0]),
            "day_name": row[1],
            "total": row[2],
            "present": row[3],
            "absent": row[4],
            "pct": round(row[3] * 100.0 / row[2], 1) if row[2] else 0,
        }
        for row in r.fetchall()
    ]

    # Subject-wise this week
    r = await db.execute(
        text("""
            SELECT
                sub.name, sub.code,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE a.status = 'present') AS present,
                ROUND(COUNT(*) FILTER (WHERE a.status = 'present') * 100.0 / NULLIF(COUNT(*), 0), 1) AS pct
            FROM attendance_records a
            JOIN subjects sub ON sub.id = a.subject_id
            WHERE a.student_id = :sid
            AND a.date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY sub.name, sub.code
            ORDER BY pct ASC NULLS LAST
        """),
        {"sid": student_id},
    )
    subjects = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    return {"daily": daily, "subjects": subjects}
