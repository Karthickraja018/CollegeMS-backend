"""
Admin Academic Management API.
CRUD for: academic_years, departments, programs, semesters, subjects, faculty_subject_assignments.
All mapped to existing schema tables — no new tables.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/academic", tags=["admin-academic"])

_admin = require_roles(UserRole.admin)
_admin_principal = require_roles(UserRole.admin, UserRole.principal)
_admin_principal_hod = require_roles(UserRole.admin, UserRole.principal, UserRole.hod)


# ─────────────────────────────────────────────────────────────────────────────
# ACADEMIC YEARS
# ─────────────────────────────────────────────────────────────────────────────

class AcademicYearCreate(BaseModel):
    label: str
    start_date: str
    end_date: str
    is_current: bool = False


@router.get("/years")
async def list_academic_years(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal),
):
    r = await db.execute(
        text("""
            SELECT id, label, start_date, end_date, is_current, created_at
            FROM academic_years
            ORDER BY start_date DESC
        """)
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/years", status_code=status.HTTP_201_CREATED)
async def create_academic_year(
    body: AcademicYearCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            INSERT INTO academic_years (college_id, label, start_date, end_date, is_current)
            VALUES (1, :label, :start_date, :end_date, :is_current)
            RETURNING id, label, start_date, end_date, is_current
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/years/{year_id}")
async def update_academic_year(
    year_id: int,
    body: AcademicYearCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            UPDATE academic_years
            SET label=:label, start_date=:start_date, end_date=:end_date, is_current=:is_current
            WHERE id=:id
            RETURNING id, label, start_date, end_date, is_current
        """),
        {**body.model_dump(), "id": year_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Academic year not found")
    return dict(zip(r.keys(), row))


@router.delete("/years/{year_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_academic_year(
    year_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    await db.execute(text("DELETE FROM academic_years WHERE id=:id"), {"id": year_id})
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENTS
# ─────────────────────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str
    code: str
    hod_id: Optional[int] = None
    phone_ext: Optional[str] = None
    email: Optional[str] = None
    established_year: Optional[int] = None
    is_active: bool = True


@router.get("/departments")
async def list_departments(
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    where = "" if is_active is None else f"WHERE d.is_active = {str(is_active).lower()}"
    r = await db.execute(
        text(f"""
            SELECT
                d.id, d.name, d.code, d.hod_id, d.phone_ext, d.email,
                d.established_year, d.is_active, d.created_at,
                u.full_name AS hod_name,
                COUNT(DISTINCT p.id) AS program_count,
                COUNT(DISTINCT s.id) AS student_count
            FROM departments d
            LEFT JOIN users u ON u.id = d.hod_id
            LEFT JOIN programs p ON p.department_id = d.id AND p.is_active = TRUE
            LEFT JOIN students s ON s.department_id = d.id AND s.status = 'active'
            {where}
            GROUP BY d.id, u.full_name
            ORDER BY d.name
        """)
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]

@router.get("/departments/overview")
async def get_departments_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        text("""
            SELECT
                d.id, d.name, d.code, d.is_active,
                u.full_name AS hod_name,
                COUNT(DISTINCT s.id) AS faculty_count,
                CASE 
                    WHEN COUNT(DISTINCT s.id) >= 4 THEN 'Healthy'
                    WHEN COUNT(DISTINCT s.id) >= 2 THEN 'Stable'
                    ELSE 'Needs Attention'
                END as health_status
            FROM departments d
            LEFT JOIN users u ON u.id = d.hod_id
            LEFT JOIN users s ON s.department_id = d.id AND s.role IN ('faculty', 'hod', 'principal') AND s.is_active = TRUE
            GROUP BY d.id, u.full_name
            ORDER BY d.name
        """)
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            INSERT INTO departments (college_id, name, code, hod_id, phone_ext, email, established_year, is_active)
            VALUES (1, :name, :code, :hod_id, :phone_ext, :email, :established_year, :is_active)
            RETURNING id, name, code, hod_id, is_active
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/departments/{dept_id}")
async def update_department(
    dept_id: int,
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            UPDATE departments
            SET name=:name, code=:code, hod_id=:hod_id, phone_ext=:phone_ext,
                email=:email, established_year=:established_year, is_active=:is_active,
                updated_at=NOW()
            WHERE id=:id
            RETURNING id, name, code, hod_id, is_active
        """),
        {**body.model_dump(), "id": dept_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Department not found")
    return dict(zip(r.keys(), row))


@router.patch("/departments/{dept_id}/toggle")
async def toggle_department(
    dept_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            UPDATE departments SET is_active = NOT is_active, updated_at = NOW()
            WHERE id = :id RETURNING id, name, is_active
        """),
        {"id": dept_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Department not found")
    return dict(zip(r.keys(), row))


# ─────────────────────────────────────────────────────────────────────────────
# PROGRAMS
# ─────────────────────────────────────────────────────────────────────────────

class ProgramCreate(BaseModel):
    department_id: int
    name: str
    code: str
    type: str  # program_type enum
    duration_years: int = 4
    total_semesters: int = 8
    total_credits: int = 160
    intake_capacity: Optional[int] = None
    is_nba_accredited: bool = False
    is_active: bool = True


@router.get("/programs")
async def list_programs(
    department_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    where = "WHERE p.is_active = TRUE"
    params: dict = {}
    if department_id:
        where += " AND p.department_id = :dept_id"
        params["dept_id"] = department_id
    r = await db.execute(
        text(f"""
            SELECT
                p.id, p.name, p.code, p.type, p.duration_years,
                p.total_semesters, p.total_credits, p.intake_capacity,
                p.is_nba_accredited, p.is_active,
                d.name AS department_name,
                d.code AS department_code,
                COUNT(DISTINCT s.id) AS student_count
            FROM programs p
            JOIN departments d ON d.id = p.department_id
            LEFT JOIN students s ON s.program_id = p.id AND s.status = 'active'
            {where}
            GROUP BY p.id, d.name, d.code
            ORDER BY d.name, p.name
        """),
        params,
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/programs", status_code=status.HTTP_201_CREATED)
async def create_program(
    body: ProgramCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            INSERT INTO programs
                (department_id, name, code, type, duration_years, total_semesters,
                 total_credits, intake_capacity, is_nba_accredited, is_active)
            VALUES
                (:department_id, :name, :code, :type, :duration_years, :total_semesters,
                 :total_credits, :intake_capacity, :is_nba_accredited, :is_active)
            RETURNING id, name, code, type, is_active
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/programs/{program_id}")
async def update_program(
    program_id: int,
    body: ProgramCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            UPDATE programs
            SET department_id=:department_id, name=:name, code=:code, type=:type,
                duration_years=:duration_years, total_semesters=:total_semesters,
                total_credits=:total_credits, intake_capacity=:intake_capacity,
                is_nba_accredited=:is_nba_accredited, is_active=:is_active,
                updated_at=NOW()
            WHERE id=:id
            RETURNING id, name, code, type, is_active
        """),
        {**body.model_dump(), "id": program_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Program not found")
    return dict(zip(r.keys(), row))


# ─────────────────────────────────────────────────────────────────────────────
# SEMESTERS
# ─────────────────────────────────────────────────────────────────────────────

class SemesterCreate(BaseModel):
    academic_year_id: int
    program_id: int
    semester_number: int
    start_date: str
    end_date: str
    status: str = "upcoming"
    working_days: Optional[int] = None


@router.get("/semesters")
async def list_semesters(
    program_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conditions = []
    params: dict = {}
    if program_id:
        conditions.append("sem.program_id = :program_id")
        params["program_id"] = program_id
    if status:
        conditions.append("sem.status = :status")
        params["status"] = status
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    r = await db.execute(
        text(f"""
            SELECT
                sem.id, sem.semester_number, sem.start_date, sem.end_date,
                sem.status, sem.working_days,
                ay.label AS academic_year,
                p.name AS program_name,
                p.code AS program_code,
                d.name AS department_name,
                COUNT(DISTINCT se.student_id) AS enrolled_students
            FROM semesters sem
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            JOIN programs p ON p.id = sem.program_id
            JOIN departments d ON d.id = p.department_id
            LEFT JOIN semester_enrollments se ON se.semester_id = sem.id
            {where}
            GROUP BY sem.id, ay.label, p.name, p.code, d.name
            ORDER BY sem.start_date DESC
        """),
        params,
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/semesters", status_code=status.HTTP_201_CREATED)
async def create_semester(
    body: SemesterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            INSERT INTO semesters
                (academic_year_id, program_id, semester_number, start_date, end_date, status, working_days)
            VALUES
                (:academic_year_id, :program_id, :semester_number, :start_date, :end_date, :status, :working_days)
            RETURNING id, semester_number, status
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/semesters/{sem_id}/status")
async def update_semester_status(
    sem_id: int,
    new_status: str = Query(..., description="upcoming|ongoing|completed|results_published"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal),
):
    r = await db.execute(
        text("""
            UPDATE semesters SET status=:status, updated_at=NOW()
            WHERE id=:id RETURNING id, status
        """),
        {"status": new_status, "id": sem_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Semester not found")
    return dict(zip(r.keys(), row))


# ─────────────────────────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────

class SubjectCreate(BaseModel):
    department_id: int
    program_id: int
    code: str
    name: str
    type: str = "theory"
    semester_number: int
    credits: int = 3
    lecture_hours: int = 3
    tutorial_hours: int = 1
    practical_hours: int = 0
    is_elective: bool = False
    regulations: Optional[str] = None
    is_active: bool = True


@router.get("/subjects")
async def list_subjects(
    department_id: Optional[int] = None,
    program_id: Optional[int] = None,
    semester_number: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conditions = ["sub.is_active = TRUE"]
    params: dict = {}
    if department_id:
        conditions.append("sub.department_id = :dept_id")
        params["dept_id"] = department_id
    if program_id:
        conditions.append("sub.program_id = :prog_id")
        params["prog_id"] = program_id
    if semester_number:
        conditions.append("sub.semester_number = :sem_num")
        params["sem_num"] = semester_number
    if search:
        conditions.append("(sub.name ILIKE :search OR sub.code ILIKE :search)")
        params["search"] = f"%{search}%"
    where = "WHERE " + " AND ".join(conditions)
    r = await db.execute(
        text(f"""
            SELECT
                sub.id, sub.code, sub.name, sub.type, sub.semester_number,
                sub.credits, sub.lecture_hours, sub.tutorial_hours,
                sub.practical_hours, sub.total_hours,
                sub.is_elective, sub.is_lab, sub.regulations, sub.is_active,
                d.name AS department_name,
                p.name AS program_name,
                COUNT(DISTINCT fsa.user_id) AS faculty_count
            FROM subjects sub
            JOIN departments d ON d.id = sub.department_id
            JOIN programs p ON p.id = sub.program_id
            LEFT JOIN faculty_subject_assignments fsa ON fsa.subject_id = sub.id
            {where}
            GROUP BY sub.id, d.name, p.name
            ORDER BY sub.semester_number, sub.name
        """),
        params,
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/subjects", status_code=status.HTTP_201_CREATED)
async def create_subject(
    body: SubjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    r = await db.execute(
        text("""
            INSERT INTO subjects
                (department_id, program_id, code, name, type, semester_number,
                 credits, lecture_hours, tutorial_hours, practical_hours,
                 is_elective, regulations, is_active)
            VALUES
                (:department_id, :program_id, :code, :name, :type, :semester_number,
                 :credits, :lecture_hours, :tutorial_hours, :practical_hours,
                 :is_elective, :regulations, :is_active)
            RETURNING id, code, name, type, semester_number, credits
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/subjects/{subject_id}")
async def update_subject(
    subject_id: int,
    body: SubjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    r = await db.execute(
        text("""
            UPDATE subjects
            SET department_id=:department_id, program_id=:program_id,
                code=:code, name=:name, type=:type, semester_number=:semester_number,
                credits=:credits, lecture_hours=:lecture_hours,
                tutorial_hours=:tutorial_hours, practical_hours=:practical_hours,
                is_elective=:is_elective, regulations=:regulations, is_active=:is_active
            WHERE id=:id
            RETURNING id, code, name, type, is_active
        """),
        {**body.model_dump(), "id": subject_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Subject not found")
    return dict(zip(r.keys(), row))


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_subject(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    """Soft-delete: sets is_active = FALSE."""
    await db.execute(
        text("UPDATE subjects SET is_active = FALSE WHERE id = :id"),
        {"id": subject_id},
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# FACULTY SUBJECT ASSIGNMENTS
# ─────────────────────────────────────────────────────────────────────────────

class FacultyAssignCreate(BaseModel):
    user_id: int
    subject_id: int
    semester_id: int
    is_primary: bool = True
    assigned_on: Optional[str] = None


@router.get("/faculty-assignments")
async def list_faculty_assignments(
    semester_id: Optional[int] = None,
    department_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conditions = []
    params: dict = {}
    if semester_id:
        conditions.append("fsa.semester_id = :semester_id")
        params["semester_id"] = semester_id
    if department_id:
        conditions.append("sub.department_id = :dept_id")
        params["dept_id"] = department_id
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    r = await db.execute(
        text(f"""
            SELECT
                fsa.id, fsa.user_id, fsa.subject_id, fsa.semester_id,
                fsa.is_primary, fsa.assigned_on,
                u.full_name AS faculty_name,
                u.employee_id,
                sub.name AS subject_name, sub.code AS subject_code,
                sem.semester_number,
                p.name AS program_name
            FROM faculty_subject_assignments fsa
            JOIN users u ON u.id = fsa.user_id
            JOIN subjects sub ON sub.id = fsa.subject_id
            JOIN semesters sem ON sem.id = fsa.semester_id
            JOIN programs p ON p.id = sem.program_id
            {where}
            ORDER BY u.full_name, sub.name
        """),
        params,
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]


@router.post("/faculty-assignments", status_code=status.HTTP_201_CREATED)
async def create_faculty_assignment(
    body: FacultyAssignCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    r = await db.execute(
        text("""
            INSERT INTO faculty_subject_assignments
                (user_id, subject_id, semester_id, is_primary, assigned_on)
            VALUES (:user_id, :subject_id, :semester_id, :is_primary, :assigned_on)
            ON CONFLICT (user_id, subject_id, semester_id) DO NOTHING
            RETURNING id
        """),
        body.model_dump(),
    )
    await db.commit()
    row = r.fetchone()
    return {"id": row[0] if row else None, "message": "Assignment created"}


@router.delete("/faculty-assignments/{assign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faculty_assignment(
    assign_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_principal_hod),
):
    await db.execute(
        text("DELETE FROM faculty_subject_assignments WHERE id = :id"), {"id": assign_id}
    )
    await db.commit()
