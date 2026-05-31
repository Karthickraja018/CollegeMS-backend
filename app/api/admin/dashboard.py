"""
Admin Dashboard API — 12 KPI widgets + AI insights.
All queries map directly to existing schema tables.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])

_admin_roles = require_roles(
    UserRole.admin, UserRole.principal, UserRole.hod
)


@router.get("/kpis")
async def get_dashboard_kpis(
    current_user: User = Depends(_admin_roles),
    db: AsyncSession = Depends(get_db),
):
    """Return all 12 admin dashboard KPI values."""
    kpis = {}

    # 1. Total Students (active)
    r = await db.execute(text("SELECT COUNT(*) FROM students WHERE status = 'active'"))
    kpis["total_students"] = r.scalar() or 0

    # 2. Total Faculty (users with role in faculty/hod)
    r = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE role IN ('faculty', 'hod') AND is_active = TRUE")
    )
    kpis["total_faculty"] = r.scalar() or 0

    # 3. Total Departments
    r = await db.execute(text("SELECT COUNT(*) FROM departments WHERE is_active = TRUE"))
    kpis["total_departments"] = r.scalar() or 0

    # 4. Total Programs
    r = await db.execute(text("SELECT COUNT(*) FROM programs WHERE is_active = TRUE"))
    kpis["total_programs"] = r.scalar() or 0

    # 5. Active Semesters (status = 'ongoing')
    r = await db.execute(text("SELECT COUNT(*) FROM semesters WHERE status = 'ongoing'"))
    kpis["active_semesters"] = r.scalar() or 0

    # 6. Average Attendance % (from materialized view)
    r = await db.execute(
        text("""
            SELECT ROUND(AVG(attendance_pct)::numeric, 1)
            FROM attendance_summary
        """)
    )
    kpis["avg_attendance"] = float(r.scalar() or 0)

    # 7. Pass Percentage (marks_records where percentage >= 50)
    r = await db.execute(
        text("""
            SELECT ROUND(
                (COUNT(*) FILTER (WHERE percentage >= 50) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 1
            )
            FROM marks_records
            WHERE is_absent = FALSE AND is_withheld = FALSE
        """)
    )
    kpis["pass_percentage"] = float(r.scalar() or 0)

    # 8. At-Risk Students (risk_score >= 60)
    r = await db.execute(
        text("SELECT COUNT(*) FROM students WHERE risk_score >= 60 AND status = 'active'")
    )
    kpis["at_risk_students"] = r.scalar() or 0

    # 9. Placement Rate (students with accepted offers / total active final-year students)
    r = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT po.application_id) AS placed,
                COUNT(DISTINCT s.id) AS total_final
            FROM students s
            LEFT JOIN placement_applications pa ON pa.student_id = s.id
            LEFT JOIN placement_offers po ON po.application_id = pa.id AND po.is_accepted = TRUE
            WHERE s.status = 'active'
        """)
    )
    row = r.fetchone()
    placed = row[0] or 0
    total = row[1] or 1
    kpis["placement_rate"] = round(placed * 100 / total, 1)

    # 10. Fee Collection — total paid vs total due
    r = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(total_paid), 0) AS collected,
                COALESCE(SUM(total_due), 0) AS total_due
            FROM fee_accounts
        """)
    )
    row = r.fetchone()
    kpis["fee_collected"] = float(row[0] or 0)
    kpis["fee_total_due"] = float(row[1] or 0)
    due = float(row[1] or 1)
    kpis["fee_collection_pct"] = round(float(row[0] or 0) * 100 / due, 1)

    # 11. Reports Generated (all time)
    r = await db.execute(text("SELECT COUNT(*) FROM reports WHERE status = 'completed'"))
    kpis["reports_generated"] = r.scalar() or 0

    # 12. AI Queries Processed (chat sessions × avg messages)
    r = await db.execute(
        text("""
            SELECT
                COUNT(*) AS sessions,
                COALESCE(SUM(jsonb_array_length(messages)), 0) AS total_messages
            FROM chat_sessions
        """)
    )
    row = r.fetchone()
    kpis["ai_sessions"] = row[0] or 0
    kpis["ai_queries_processed"] = row[1] or 0

    return kpis


@router.get("/ai-insights")
async def get_ai_insights(
    current_user: User = Depends(_admin_roles),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate data-driven insights from live DB stats.
    Returns a list of insight objects with type, message, and severity.
    """
    insights = []

    # Attendance insight
    r = await db.execute(
        text("""
            SELECT
                ROUND(AVG(attendance_pct)::numeric, 1) AS avg_att,
                COUNT(*) FILTER (WHERE attendance_pct < 75) AS low_att_count
            FROM attendance_summary
        """)
    )
    row = r.fetchone()
    if row and row[0] is not None:
        avg = float(row[0])
        low = row[1] or 0
        if avg < 75:
            insights.append({
                "type": "warning",
                "icon": "alert-triangle",
                "title": "Low Overall Attendance",
                "body": f"College-wide attendance is {avg}% — below the 75% minimum threshold.",
                "metric": avg,
            })
        else:
            insights.append({
                "type": "success",
                "icon": "trending-up",
                "title": f"Attendance at {avg}%",
                "body": f"{low} student-subject combinations are still below 75% and need attention.",
                "metric": avg,
            })

    # At-risk insight
    r = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE risk_score >= 80) AS critical,
                COUNT(*) FILTER (WHERE risk_score >= 60 AND risk_score < 80) AS high,
                COUNT(*) FILTER (WHERE risk_score >= 40 AND risk_score < 60) AS medium
            FROM students
            WHERE status = 'active'
        """)
    )
    row = r.fetchone()
    if row:
        critical, high, medium = row[0] or 0, row[1] or 0, row[2] or 0
        if critical > 0:
            insights.append({
                "type": "critical",
                "icon": "users",
                "title": "Critical Risk Alert",
                "body": f"{critical} students are at critical risk. Immediate intervention required.",
                "metric": critical,
            })
        elif high > 0:
            insights.append({
                "type": "warning",
                "icon": "users",
                "title": "High-Risk Students",
                "body": f"{high} students are at high risk of failing this semester.",
                "metric": high,
            })

    # Best-performing department
    r = await db.execute(
        text("""
            SELECT d.name, ROUND(AVG(att.attendance_pct)::numeric, 1) AS avg_att
            FROM departments d
            JOIN students s ON s.department_id = d.id AND s.status = 'active'
            JOIN attendance_summary att ON att.student_id = s.id
            GROUP BY d.name
            ORDER BY avg_att DESC
            LIMIT 1
        """)
    )
    row = r.fetchone()
    if row and row[0]:
        insights.append({
            "type": "success",
            "icon": "award",
            "title": f"{row[0]} leads in Attendance",
            "body": f"{row[0]} department has the highest attendance at {row[1]}%.",
            "metric": float(row[1] or 0),
        })

    # Fee collection insight
    r = await db.execute(
        text("""
            SELECT
                ROUND((SUM(total_paid) * 100.0 / NULLIF(SUM(total_due), 0))::numeric, 1) AS collection_pct,
                COUNT(*) FILTER (WHERE status IN ('due', 'overdue')) AS pending_count
            FROM fee_accounts
        """)
    )
    row = r.fetchone()
    if row and row[0] is not None:
        pct = float(row[0])
        pending = row[1] or 0
        if pct < 80:
            insights.append({
                "type": "warning",
                "icon": "dollar-sign",
                "title": "Fee Collection Below Target",
                "body": f"Only {pct}% of fees collected. {pending} accounts have outstanding dues.",
                "metric": pct,
            })
        else:
            insights.append({
                "type": "success",
                "icon": "dollar-sign",
                "title": f"Fee Collection at {pct}%",
                "body": f"{pending} accounts still have outstanding balances.",
                "metric": pct,
            })

    # Placement insight
    r = await db.execute(
        text("""
            SELECT COUNT(*) FROM placement_drives
            WHERE drive_date >= CURRENT_DATE AND status = 'upcoming'
        """)
    )
    upcoming_drives = r.scalar() or 0
    if upcoming_drives > 0:
        insights.append({
            "type": "info",
            "icon": "briefcase",
            "title": f"{upcoming_drives} Upcoming Placement Drive(s)",
            "body": f"{upcoming_drives} placement drive(s) scheduled. Ensure student profiles are updated.",
            "metric": upcoming_drives,
        })

    return {"insights": insights, "generated_at": "now"}


@router.get("/recent-activity")
async def get_recent_activity(
    limit: int = 10,
    current_user: User = Depends(_admin_roles),
    db: AsyncSession = Depends(get_db),
):
    """Return recent audit log entries for the activity timeline."""
    r = await db.execute(
        text("""
            SELECT
                al.id,
                al.table_name,
                al.action,
                al.created_at,
                u.full_name AS user_name,
                u.role AS user_role
            FROM audit_logs al
            LEFT JOIN users u ON u.id = al.user_id
            ORDER BY al.created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = r.fetchall()
    cols = list(r.keys())
    return [dict(zip(cols, row)) for row in rows]
