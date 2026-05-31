"""
Analytics API — pre-computed aggregations for the dashboard.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Main dashboard KPIs."""
    stats = {}

    # Total students
    r = await db.execute(text("SELECT COUNT(*) FROM students"))
    stats["total_students"] = r.scalar()

    # Average attendance
    r = await db.execute(text("""
        SELECT ROUND(
            (COUNT(CASE WHEN status = 'present' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1
        ) FROM attendance
    """))
    stats["avg_attendance"] = float(r.scalar() or 0)

    # At-risk students (risk_score > 60)
    r = await db.execute(text("SELECT COUNT(*) FROM students WHERE risk_score > 60"))
    stats["at_risk_count"] = r.scalar()

    # Total departments
    r = await db.execute(text("SELECT COUNT(*) FROM departments"))
    stats["total_departments"] = r.scalar()

    # Pass percentage (marks >= 40%)
    r = await db.execute(text("""
        SELECT ROUND(
            (COUNT(CASE WHEN marks_obtained * 100.0 / NULLIF(max_marks, 0) >= 40 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1
        ) FROM marks
    """))
    stats["pass_percentage"] = float(r.scalar() or 0)

    # Total reports generated
    r = await db.execute(text("SELECT COUNT(*) FROM reports"))
    stats["total_reports"] = r.scalar()

    return stats


@router.get("/attendance-trend")
async def get_attendance_trend(
    months: int = 6,
    department_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Monthly attendance trend for charts."""
    dept_filter = "AND s.department_id = :dept_id" if department_id else ""
    sql = text(f"""
        SELECT
            TO_CHAR(a.date, 'Mon YYYY') AS month,
            DATE_TRUNC('month', a.date) AS month_order,
            ROUND(
                (COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1
            ) AS attendance_pct
        FROM attendance a
        JOIN students s ON s.id = a.student_id
        WHERE a.date >= NOW() - (:months * INTERVAL '1 month')
        {dept_filter}
        GROUP BY TO_CHAR(a.date, 'Mon YYYY'), DATE_TRUNC('month', a.date)
        ORDER BY month_order
    """)
    params = {"months": months}
    if department_id:
        params["dept_id"] = department_id

    result = await db.execute(sql, params)
    rows = result.fetchall()
    return [{"month": r[0], "attendance": float(r[2] or 0)} for r in rows]


@router.get("/department-performance")
async def get_department_performance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Department-wise attendance and marks comparison."""
    sql = text("""
        SELECT
            d.name AS department,
            d.code,
            COUNT(DISTINCT s.id) AS student_count,
            ROUND(
                (COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0 / NULLIF(COUNT(a.id), 0))::numeric, 1
            ) AS attendance_pct,
            ROUND(
                (AVG(m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0)))::numeric, 1
            ) AS avg_marks_pct
        FROM departments d
        LEFT JOIN students s ON s.department_id = d.id
        LEFT JOIN attendance a ON a.student_id = s.id
        LEFT JOIN marks m ON m.student_id = s.id
        GROUP BY d.name, d.code
        ORDER BY d.name
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    cols = list(result.keys())
    return [dict(zip(cols, row)) for row in rows]


@router.get("/subject-pass-rates")
async def get_subject_pass_rates(
    department_id: int | None = None,
    semester: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subject-wise pass percentage."""
    conditions = []
    params = {}
    if department_id:
        conditions.append("sub.department_id = :dept_id")
        params["dept_id"] = department_id
    if semester:
        conditions.append("sub.semester = :semester")
        params["semester"] = semester

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = text(f"""
        SELECT
            sub.name AS subject,
            sub.code,
            sub.semester,
            d.name AS department,
            COUNT(m.id) AS total,
            COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) AS passed,
            ROUND(
                (COUNT(CASE WHEN m.marks_obtained * 100.0 / NULLIF(m.max_marks, 0) >= 40 THEN 1 END) * 100.0 / NULLIF(COUNT(m.id), 0))::numeric, 1
            ) AS pass_rate
        FROM subjects sub
        JOIN departments d ON d.id = sub.department_id
        LEFT JOIN marks m ON m.subject_id = sub.id
        {where}
        GROUP BY sub.name, sub.code, sub.semester, d.name
        ORDER BY pass_rate ASC
        LIMIT 30
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()
    cols = list(result.keys())
    return [dict(zip(cols, row)) for row in rows]
