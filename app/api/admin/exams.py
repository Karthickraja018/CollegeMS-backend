"""
Admin — Examinations & Marks API
Tables: exam_schedules, marks_records, marks_summary (MV)
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/exams", tags=["Admin – Examinations"])



@router.get("/marks")
def list_marks(
    semester_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    exam_type: Optional[str] = None,
    student_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if semester_id:
        where.append("mr.semester_id = :semester_id")
        params["semester_id"] = semester_id
    if subject_id:
        where.append("mr.subject_id = :subject_id")
        params["subject_id"] = subject_id
    if exam_type:
        where.append("mr.exam_type = :exam_type")
        params["exam_type"] = exam_type
    if student_id:
        where.append("mr.student_id = :student_id")
        params["student_id"] = student_id

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            mr.id, mr.exam_type, mr.marks_obtained, mr.max_marks, mr.percentage,
            mr.grade, mr.grade_points, mr.is_absent, mr.is_withheld, mr.remarks,
            mr.entered_at,
            st.name AS student_name, st.roll_number,
            sub.code AS subject_code, sub.name AS subject_name,
            u.full_name AS entered_by_name
        FROM marks_records mr
        JOIN students st ON st.id = mr.student_id
        JOIN subjects sub ON sub.id = mr.subject_id
        JOIN departments d ON d.id = sub.department_id
        LEFT JOIN users u ON u.id = mr.entered_by
        WHERE d.college_id = :college_id
          {where_sql}
        ORDER BY mr.entered_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM marks_records mr
        JOIN subjects sub ON sub.id = mr.subject_id
        JOIN departments d ON d.id = sub.department_id
        WHERE d.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.get("/results/analysis")
def results_analysis(
    semester_id: int,
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Grade distribution and pass/fail analysis from marks_summary."""
    college_id = current_user.college_id
    params: dict = {"college_id": college_id, "semester_id": semester_id}
    dept_clause = "AND d.id = :department_id" if department_id else ""
    if department_id:
        params["department_id"] = department_id

    grade_dist = db.execute(text(f"""
        SELECT
            mr.grade,
            COUNT(*) AS count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) AS pct
        FROM marks_records mr
        JOIN subjects sub ON sub.id = mr.subject_id
        JOIN departments d ON d.id = sub.department_id
        WHERE d.college_id = :college_id
          AND mr.semester_id = :semester_id
          {dept_clause}
          AND mr.grade IS NOT NULL
        GROUP BY mr.grade
        ORDER BY count DESC
    """), params).fetchall()

    subject_pass_rate = db.execute(text(f"""
        SELECT
            sub.code AS subject_code,
            sub.name AS subject_name,
            COUNT(DISTINCT ms.student_id)                                         AS total,
            COUNT(DISTINCT ms.student_id) FILTER (WHERE ms.has_arrear = FALSE)    AS passed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE ms.has_arrear = FALSE) / NULLIF(COUNT(*), 0), 2
            )                                                                      AS pass_rate,
            ROUND(AVG(ms.avg_grade_points), 2)                                    AS avg_gpa
        FROM marks_summary ms
        JOIN subjects sub ON sub.id = ms.subject_id
        JOIN departments d ON d.id = sub.department_id
        WHERE d.college_id = :college_id
          AND ms.semester_id = :semester_id
          {dept_clause}
        GROUP BY sub.id, sub.code, sub.name
        ORDER BY pass_rate ASC
    """), params).fetchall()

    toppers = db.execute(text(f"""
        SELECT
            st.name, st.roll_number,
            d.name AS department_name,
            ROUND(AVG(ms.avg_grade_points), 2) AS avg_gpa,
            SUM(CASE WHEN ms.has_arrear THEN 1 ELSE 0 END) AS arrear_count
        FROM marks_summary ms
        JOIN students st ON st.id = ms.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          AND ms.semester_id = :semester_id
          {dept_clause}
        GROUP BY st.id, st.name, st.roll_number, d.name
        ORDER BY avg_gpa DESC
        LIMIT 10
    """), params).fetchall()

    return {
        "grade_distribution": [dict(r._mapping) for r in grade_dist],
        "subject_pass_rates": [dict(r._mapping) for r in subject_pass_rate],
        "toppers": [dict(r._mapping) for r in toppers],
    }


