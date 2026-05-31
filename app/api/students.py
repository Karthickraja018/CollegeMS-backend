"""
Students API — list, filter, and retrieve student data.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.student import Student
from app.models.department import Department

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def list_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    department_id: int | None = None,
    semester: int | None = None,
    search: str | None = None,
    risk_min: float | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated student list with filters."""
    query = (
        select(Student, Department.name.label("department_name"))
        .join(Department, Department.id == Student.department_id)
    )

    if department_id:
        query = query.where(Student.department_id == department_id)
    if semester:
        query = query.where(Student.semester == semester)
    if search:
        query = query.where(
            Student.name.ilike(f"%{search}%") | Student.roll_number.ilike(f"%{search}%")
        )
    if risk_min is not None:
        query = query.where(Student.risk_score >= risk_min)

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()

    # Paginate
    query = query.order_by(Student.name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    students = []
    for s, dept_name in rows:
        students.append({
            "id": s.id,
            "roll_number": s.roll_number,
            "name": s.name,
            "email": s.email,
            "department": dept_name,
            "department_id": s.department_id,
            "semester": s.semester,
            "batch": s.batch,
            "section": s.section,
            "risk_score": s.risk_score,
        })

    return {
        "data": students,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/{student_id}")
async def get_student(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single student with attendance and marks summary."""
    from sqlalchemy import text
    result = await db.execute(
        select(Student, Department.name.label("dept_name"))
        .join(Department)
        .where(Student.id == student_id)
    )
    row = result.first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Student not found")

    student, dept_name = row

    # Attendance summary
    att = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN status = 'present' THEN 1 END) AS present,
            ROUND(COUNT(CASE WHEN status = 'present' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) AS pct
        FROM attendance WHERE student_id = :sid
    """), {"sid": student_id})
    att_row = att.fetchone()

    # Marks summary
    marks = await db.execute(text("""
        SELECT
            sub.name AS subject,
            m.exam_type,
            ROUND(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0), 1) AS percentage
        FROM marks m JOIN subjects sub ON sub.id = m.subject_id
        WHERE m.student_id = :sid
        ORDER BY sub.name, m.exam_type
    """), {"sid": student_id})
    marks_rows = [dict(zip(marks.keys(), r)) for r in marks.fetchall()]

    return {
        "id": student.id,
        "roll_number": student.roll_number,
        "name": student.name,
        "email": student.email,
        "department": dept_name,
        "semester": student.semester,
        "batch": student.batch,
        "section": student.section,
        "risk_score": student.risk_score,
        "attendance": {
            "total_classes": att_row[0] if att_row else 0,
            "present": att_row[1] if att_row else 0,
            "percentage": float(att_row[2]) if att_row and att_row[2] else 0,
        },
        "marks": marks_rows,
    }
