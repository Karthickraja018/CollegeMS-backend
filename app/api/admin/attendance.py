"""
Admin — Attendance Management API
Tables: attendance_records, attendance_summary (MV), students, subjects, semesters
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional
from datetime import date

router = APIRouter(prefix="/admin/attendance", tags=["Admin – Attendance"])


@router.get("/summary")
def attendance_summary(
    semester_id: Optional[int] = None,
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Aggregate attendance by subject for the given semester / department."""
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}

    sem_clause = "AND s.id = :semester_id" if semester_id else ""
    dept_clause = "AND d.id = :department_id" if department_id else ""
    if semester_id:
        params["semester_id"] = semester_id
    if department_id:
        params["department_id"] = department_id

    rows = db.execute(text(f"""
        SELECT
            sub.id           AS subject_id,
            sub.code         AS subject_code,
            sub.name         AS subject_name,
            d.name           AS department_name,
            d.code           AS dept_code,
            sem.semester_number,
            COUNT(DISTINCT asum.student_id)                              AS enrolled,
            ROUND(AVG(asum.attendance_pct), 2)                           AS avg_attendance,
            COUNT(DISTINCT asum.student_id)
                FILTER (WHERE asum.attendance_pct < 75)                  AS below_75,
            COUNT(DISTINCT asum.student_id)
                FILTER (WHERE asum.attendance_pct < 50)                  AS below_50,
            SUM(asum.total_classes)                                      AS total_classes,
            SUM(asum.present_count)                                      AS total_present
        FROM attendance_summary asum
        JOIN subjects sub ON sub.id = asum.subject_id
        JOIN departments d ON d.id = sub.department_id
        JOIN semesters sem ON sem.id = asum.semester_id
        WHERE d.college_id = :college_id
          {sem_clause}
          {dept_clause}
        GROUP BY sub.id, sub.code, sub.name, d.name, d.code, sem.semester_number
        ORDER BY avg_attendance ASC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/defaulters")
def attendance_defaulters(
    semester_id: Optional[int] = None,
    department_id: Optional[int] = None,
    threshold: float = 75.0,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Students whose average attendance is below the given threshold."""
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "threshold": threshold, "limit": page_size, "offset": offset}

    sem_clause = "AND asum.semester_id = :semester_id" if semester_id else ""
    dept_clause = "AND d.id = :department_id" if department_id else ""
    if semester_id:
        params["semester_id"] = semester_id
    if department_id:
        params["department_id"] = department_id

    rows = db.execute(text(f"""
        SELECT
            st.id,
            st.name,
            st.roll_number,
            st.email,
            d.name          AS department_name,
            p.code          AS program_code,
            st.current_semester,
            st.batch,
            sub.code        AS subject_code,
            sub.name        AS subject_name,
            asum.attendance_pct,
            asum.present_count,
            asum.absent_count,
            asum.total_classes
        FROM attendance_summary asum
        JOIN students st ON st.id = asum.student_id
        JOIN subjects sub ON sub.id = asum.subject_id
        JOIN departments d ON d.id = st.department_id
        JOIN programs p ON p.id = st.program_id
        WHERE d.college_id = :college_id
          AND asum.attendance_pct < :threshold
          {sem_clause}
          {dept_clause}
        ORDER BY asum.attendance_pct ASC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM attendance_summary asum
        JOIN students st ON st.id = asum.student_id
        JOIN subjects sub ON sub.id = asum.subject_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          AND asum.attendance_pct < :threshold
          {sem_clause}
          {dept_clause}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/trends")
def attendance_trends(
    semester_id: Optional[int] = None,
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Monthly attendance trend for charts."""
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}

    sem_clause = "AND ar.semester_id = :semester_id" if semester_id else ""
    dept_clause = "AND d.id = :department_id" if department_id else ""
    if semester_id:
        params["semester_id"] = semester_id
    if department_id:
        params["department_id"] = department_id

    rows = db.execute(text(f"""
        SELECT
            TO_CHAR(ar.date, 'YYYY-MM')                              AS month,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE ar.status IN ('present','od','duty_leave'))
                / NULLIF(COUNT(*), 0), 2
            )                                                        AS attendance_pct,
            COUNT(*) FILTER (WHERE ar.status = 'absent')            AS absent_count,
            COUNT(*)                                                 AS total_classes
        FROM attendance_records ar
        JOIN subjects sub ON sub.id = ar.subject_id
        JOIN departments d ON d.id = sub.department_id
        WHERE d.college_id = :college_id
          {sem_clause}
          {dept_clause}
        GROUP BY TO_CHAR(ar.date, 'YYYY-MM')
        ORDER BY month
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/department-heatmap")
def attendance_dept_heatmap(
    semester_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Per-department attendance heatmap data."""
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}
    sem_clause = "AND asum.semester_id = :semester_id" if semester_id else ""
    if semester_id:
        params["semester_id"] = semester_id

    rows = db.execute(text(f"""
        SELECT
            d.id               AS department_id,
            d.name             AS department_name,
            d.code             AS dept_code,
            ROUND(AVG(asum.attendance_pct), 2)            AS avg_pct,
            COUNT(DISTINCT asum.student_id)               AS total_students,
            COUNT(DISTINCT asum.student_id)
                FILTER (WHERE asum.attendance_pct < 75)   AS defaulters
        FROM attendance_summary asum
        JOIN students st ON st.id = asum.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          {sem_clause}
        GROUP BY d.id, d.name, d.code
        ORDER BY avg_pct ASC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


