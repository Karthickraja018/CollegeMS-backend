"""
Admin — AI Operations API
Tables: chat_sessions, at_risk_snapshots, reports
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/ai", tags=["Admin – AI Operations"])


@router.get("/stats")
def ai_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Aggregated AI usage metrics."""
    college_id = current_user.college_id

    chat_stats = db.execute(text("""
        SELECT
            COUNT(*)                                   AS total_sessions,
            COUNT(DISTINCT cs.user_id)                 AS unique_users,
            COUNT(*) FILTER (WHERE
                cs.created_at >= NOW() - INTERVAL '7 days') AS sessions_last_7d,
            COUNT(*) FILTER (WHERE
                cs.created_at >= NOW() - INTERVAL '24 hours') AS sessions_today,
            ROUND(AVG(JSONB_ARRAY_LENGTH(cs.messages)), 1) AS avg_messages_per_session
        FROM chat_sessions cs
        JOIN users u ON u.id = cs.user_id
        WHERE u.college_id = :college_id
    """), {"college_id": college_id}).fetchone()

    by_agent = db.execute(text("""
        SELECT
            COALESCE(cs.last_agent, 'unknown') AS agent,
            COUNT(*) AS sessions
        FROM chat_sessions cs
        JOIN users u ON u.id = cs.user_id
        WHERE u.college_id = :college_id
        GROUP BY cs.last_agent ORDER BY sessions DESC
    """), {"college_id": college_id}).fetchall()

    risk_stats = db.execute(text("""
        SELECT
            COUNT(DISTINCT student_id)                          AS students_scanned,
            COUNT(DISTINCT student_id)
                FILTER (WHERE risk_score >= 80)                  AS critical,
            COUNT(DISTINCT student_id)
                FILTER (WHERE risk_score >= 60 AND risk_score < 80) AS high,
            COUNT(DISTINCT student_id)
                FILTER (WHERE risk_score >= 40 AND risk_score < 60) AS medium,
            MAX(snapshot_date)                                  AS last_scan_date
        FROM at_risk_snapshots ars
        JOIN students st ON st.id = ars.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          AND snapshot_date = (SELECT MAX(snapshot_date) FROM at_risk_snapshots)
    """), {"college_id": college_id}).fetchone()

    report_stats = db.execute(text("""
        SELECT
            COUNT(*) AS total_reports,
            COUNT(*) FILTER (WHERE status = 'completed')    AS completed,
            COUNT(*) FILTER (WHERE status = 'failed')       AS failed,
            COUNT(*) FILTER (WHERE status IN ('queued','generating')) AS in_progress
        FROM reports WHERE college_id = :college_id
    """), {"college_id": college_id}).fetchone()

    daily_usage = db.execute(text("""
        SELECT
            TO_CHAR(cs.created_at, 'YYYY-MM-DD') AS day,
            COUNT(*)                              AS sessions
        FROM chat_sessions cs
        JOIN users u ON u.id = cs.user_id
        WHERE u.college_id = :college_id
          AND cs.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY day ORDER BY day
    """), {"college_id": college_id}).fetchall()

    return {
        "chat": dict(chat_stats._mapping),
        "by_agent": [dict(r._mapping) for r in by_agent],
        "risk_monitoring": dict(risk_stats._mapping) if risk_stats else {},
        "reports": dict(report_stats._mapping),
        "daily_usage": [dict(r._mapping) for r in daily_usage],
    }


@router.get("/sessions")
def recent_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size

    rows = db.execute(text("""
        SELECT
            cs.id, cs.title, cs.last_agent, cs.created_at, cs.updated_at,
            JSONB_ARRAY_LENGTH(cs.messages) AS message_count,
            u.full_name AS user_name, u.email, u.role
        FROM chat_sessions cs
        JOIN users u ON u.id = cs.user_id
        WHERE u.college_id = :college_id
        ORDER BY cs.updated_at DESC
        LIMIT :limit OFFSET :offset
    """), {"college_id": college_id, "limit": page_size, "offset": offset}).fetchall()

    return [dict(r._mapping) for r in rows]


@router.post("/risk/trigger-scan")
def trigger_risk_scan(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """
    Manual trigger to run at-risk scoring for all active students.
    In production this would queue a Celery task. Here we run a simplified scoring.
    """
    college_id = current_user.college_id

    # Mark students with low attendance as at-risk (simplified inline scoring)
    updated = db.execute(text("""
        UPDATE students st
        SET risk_score = LEAST(100, COALESCE((
            SELECT ROUND(
                (CASE WHEN AVG(asum.attendance_pct) < 60 THEN 50
                      WHEN AVG(asum.attendance_pct) < 75 THEN 30
                      ELSE 0 END)
                + (CASE WHEN COUNT(ms.student_id) FILTER (WHERE ms.has_arrear) > 2 THEN 30
                        WHEN COUNT(ms.student_id) FILTER (WHERE ms.has_arrear) > 0 THEN 15
                        ELSE 0 END)
            , 2)
            FROM attendance_summary asum
            LEFT JOIN marks_summary ms ON ms.student_id = st.id
            WHERE asum.student_id = st.id
        ), 0))
        WHERE st.college_id = :college_id AND st.status = 'active'
        RETURNING id
    """), {"college_id": college_id})
    db.commit()

    return {"success": True, "message": "Risk scan triggered", "students_updated": updated.rowcount}


