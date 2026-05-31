"""
Admin Student Management API.
Extended student endpoints: 360° profile, bulk operations, at-risk view.
Mapped to: students, semester_enrollments, attendance_summary,
           marks_summary, fee_accounts, placement_applications, at_risk_snapshots.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/students", tags=["admin-students"])

_admin = require_roles(UserRole.admin)
_admin_principal_hod = require_roles(UserRole.admin, UserRole.principal, UserRole.hod)


@router.get("")
async def list_students(
    department_id: Optional[int] = None,
    program_id: Optional[int] = None,
    status: Optional[str] = None,
    batch: Optional[str] = None,
    current_semester: Optional[int] = None,
    risk_level: Optional[str] = None,  # low|medium|high|critical
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full paginated student list with rich filters."""
    conditions = []
    params: dict = {"offset": (page - 1) * page_size, "limit": page_size}

    if department_id:
        conditions.append("s.department_id = :dept_id")
        params["dept_id"] = department_id
    if program_id:
        conditions.append("s.program_id = :prog_id")
        params["prog_id"] = program_id
    if status:
        conditions.append("s.status = :status")
        params["status"] = status
    else:
        conditions.append("s.status != 'discontinued'")
    if batch:
        conditions.append("s.batch = :batch")
        params["batch"] = batch
    if current_semester:
        conditions.append("s.current_semester = :sem")
        params["sem"] = current_semester
    if risk_level:
        risk_ranges = {
            "critical": "s.risk_score >= 80",
            "high": "s.risk_score >= 60 AND s.risk_score < 80",
            "medium": "s.risk_score >= 40 AND s.risk_score < 60",
            "low": "s.risk_score < 40",
        }
        if risk_level in risk_ranges:
            conditions.append(f"({risk_ranges[risk_level]})")
    if search:
        conditions.append(
            "(s.name ILIKE :search OR s.roll_number ILIKE :search OR s.email ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    r = await db.execute(
        text(f"""
            SELECT
                s.id, s.roll_number, s.name, s.email, s.phone, s.gender,
                s.batch, s.current_semester, s.section, s.status,
                s.risk_score, s.is_hosteller, s.lateral_entry,
                d.name AS department_name, d.code AS department_code,
                p.name AS program_name, p.code AS program_code,
                fa.status AS fee_status, fa.balance AS fee_balance,
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_attendance
            FROM students s
            JOIN departments d ON d.id = s.department_id
            JOIN programs p ON p.id = s.program_id
            LEFT JOIN fee_accounts fa ON fa.student_id = s.id
            LEFT JOIN attendance_summary att ON att.student_id = s.id
            {where}
            GROUP BY s.id, d.name, d.code, p.name, p.code, fa.status, fa.balance
            ORDER BY s.name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = r.fetchall()
    data = [dict(zip(r.keys(), row)) for row in rows]

    count_params = {k: v for k, v in params.items() if k not in ("offset", "limit")}
    count_r = await db.execute(
        text(f"""
            SELECT COUNT(DISTINCT s.id)
            FROM students s
            JOIN departments d ON d.id = s.department_id
            JOIN programs p ON p.id = s.program_id
            LEFT JOIN fee_accounts fa ON fa.student_id = s.id
            {where}
        """),
        count_params,
    )
    total = count_r.scalar() or 0
    return {"data": data, "total": total, "page": page, "page_size": page_size}


@router.get("/{student_id}")
async def get_student_profile(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """360° student profile."""
    # Core profile
    r = await db.execute(
        text("""
            SELECT s.*, d.name AS department_name, p.name AS program_name, p.code AS program_code
            FROM students s
            JOIN departments d ON d.id = s.department_id
            JOIN programs p ON p.id = s.program_id
            WHERE s.id = :id
        """),
        {"id": student_id},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    profile = dict(zip(r.keys(), row))

    # Attendance summary (current semester)
    r = await db.execute(
        text("""
            SELECT
                sub.name AS subject_name, sub.code AS subject_code,
                att.present_count, att.absent_count, att.total_classes, att.attendance_pct,
                sem.semester_number
            FROM attendance_summary att
            JOIN subjects sub ON sub.id = att.subject_id
            JOIN semesters sem ON sem.id = att.semester_id
            WHERE att.student_id = :id
            ORDER BY sem.semester_number DESC, sub.name
            LIMIT 20
        """),
        {"id": student_id},
    )
    profile["attendance"] = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Marks summary
    r = await db.execute(
        text("""
            SELECT
                sub.name AS subject_name, sub.code AS subject_code,
                ms.cia_avg_pct, ms.sem_end_pct, ms.avg_grade_points,
                ms.has_arrear, ms.absent_exams,
                sem.semester_number
            FROM marks_summary ms
            JOIN subjects sub ON sub.id = ms.subject_id
            JOIN semesters sem ON sem.id = ms.semester_id
            WHERE ms.student_id = :id
            ORDER BY sem.semester_number DESC, sub.name
            LIMIT 20
        """),
        {"id": student_id},
    )
    profile["marks"] = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Fee accounts
    r = await db.execute(
        text("""
            SELECT fa.id, fa.academic_year, fa.total_due, fa.total_paid,
                   fa.concession, fa.balance, fa.status, fa.due_date
            FROM fee_accounts fa
            WHERE fa.student_id = :id
            ORDER BY fa.academic_year DESC
        """),
        {"id": student_id},
    )
    profile["fees"] = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Placement applications
    r = await db.execute(
        text("""
            SELECT
                pa.id, pa.status, pa.applied_at,
                pd.company_name, pd.job_role, pd.ctc_lpa, pd.drive_date,
                po.ctc_offered, po.is_accepted
            FROM placement_applications pa
            JOIN placement_drives pd ON pd.id = pa.drive_id
            LEFT JOIN placement_offers po ON po.application_id = pa.id
            WHERE pa.student_id = :id
            ORDER BY pa.applied_at DESC
        """),
        {"id": student_id},
    )
    profile["placements"] = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Latest risk snapshot
    r = await db.execute(
        text("""
            SELECT risk_score, flags, snapshot_date, triggered_by
            FROM at_risk_snapshots
            WHERE student_id = :id
            ORDER BY snapshot_date DESC
            LIMIT 5
        """),
        {"id": student_id},
    )
    profile["risk_history"] = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    return profile


@router.get("/at-risk/dashboard")
async def get_at_risk_dashboard(
    department_id: Optional[int] = None,
    risk_level: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """At-risk student dashboard with aggregates."""
    params: dict = {}
    dept_filter = ""
    if department_id:
        dept_filter = "AND s.department_id = :dept_id"
        params["dept_id"] = department_id

    r = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE s.risk_score >= 80) AS critical_count,
                COUNT(*) FILTER (WHERE s.risk_score >= 60 AND s.risk_score < 80) AS high_count,
                COUNT(*) FILTER (WHERE s.risk_score >= 40 AND s.risk_score < 60) AS medium_count,
                COUNT(*) FILTER (WHERE s.risk_score < 40) AS low_count,
                COUNT(*) AS total_active,
                ROUND(AVG(s.risk_score)::numeric, 1) AS avg_risk_score
            FROM students s
            WHERE s.status = 'active' {dept_filter}
        """),
        params,
    )
    row = r.fetchone()
    aggregates = dict(zip(r.keys(), row))

    # At-risk students list
    risk_where = "s.risk_score >= 40 AND s.status = 'active'"
    if department_id:
        risk_where += " AND s.department_id = :dept_id"
    if risk_level:
        risk_ranges = {
            "critical": "s.risk_score >= 80",
            "high": "s.risk_score >= 60 AND s.risk_score < 80",
            "medium": "s.risk_score >= 40 AND s.risk_score < 60",
        }
        if risk_level in risk_ranges:
            risk_where = f"{risk_ranges[risk_level]} AND s.status = 'active'"
            if department_id:
                risk_where += " AND s.department_id = :dept_id"

    r = await db.execute(
        text(f"""
            SELECT
                s.id, s.roll_number, s.name, s.batch, s.current_semester,
                s.risk_score, s.risk_flags,
                d.name AS department_name,
                p.name AS program_name,
                ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_attendance,
                COUNT(ms.has_arrear) FILTER (WHERE ms.has_arrear = TRUE) AS arrear_count
            FROM students s
            JOIN departments d ON d.id = s.department_id
            JOIN programs p ON p.id = s.program_id
            LEFT JOIN attendance_summary att ON att.student_id = s.id
            LEFT JOIN marks_summary ms ON ms.student_id = s.id
            WHERE {risk_where}
            GROUP BY s.id, d.name, p.name
            ORDER BY s.risk_score DESC
            LIMIT 50
        """),
        params,
    )
    students = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    # Department breakdown
    r = await db.execute(
        text(f"""
            SELECT
                d.name AS department_name,
                d.code,
                COUNT(*) FILTER (WHERE s.risk_score >= 80) AS critical,
                COUNT(*) FILTER (WHERE s.risk_score >= 60 AND s.risk_score < 80) AS high,
                COUNT(*) FILTER (WHERE s.risk_score >= 40 AND s.risk_score < 60) AS medium,
                COUNT(*) AS total
            FROM students s
            JOIN departments d ON d.id = s.department_id
            WHERE s.status = 'active' {dept_filter}
            GROUP BY d.name, d.code
            ORDER BY critical DESC
        """),
        params,
    )
    by_dept = [dict(zip(r.keys(), row)) for row in r.fetchall()]

    return {
        "aggregates": aggregates,
        "students": students,
        "by_department": by_dept,
    }


class StudentStatusUpdate(BaseModel):
    new_status: str  # active|detained|transferred_out|passed_out|discontinued


@router.post("/{student_id}/status")
async def update_student_status(
    student_id: int,
    body: StudentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    r = await db.execute(
        text("""
            UPDATE students SET status=:status, updated_at=NOW()
            WHERE id=:id RETURNING id, name, status
        """),
        {"status": body.new_status, "id": student_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    return dict(zip(r.keys(), row))


@router.post("/{student_id}/promote")
async def promote_student(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    """Increment current_semester by 1."""
    r = await db.execute(
        text("""
            UPDATE students
            SET current_semester = current_semester + 1, updated_at = NOW()
            WHERE id = :id AND status = 'active'
            RETURNING id, name, current_semester
        """),
        {"id": student_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found or not active")
    return dict(zip(r.keys(), row))
