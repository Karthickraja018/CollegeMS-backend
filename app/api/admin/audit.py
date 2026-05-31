"""
Admin — Audit Logs API
Table: audit_logs
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/audit", tags=["Admin – Audit"])


@router.get("/logs")
def list_audit_logs(
    user_id: Optional[int] = None,
    table_name: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if user_id:
        where.append("al.user_id = :user_id")
        params["user_id"] = user_id
    if table_name:
        where.append("al.table_name = :table_name")
        params["table_name"] = table_name
    if action:
        where.append("al.action = :action")
        params["action"] = action
    if date_from:
        where.append("al.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("al.created_at <= :date_to")
        params["date_to"] = date_to

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            al.id, al.table_name, al.record_id, al.action,
            al.old_data, al.new_data, al.ip_address, al.user_agent,
            al.created_at,
            u.full_name AS user_name, u.email AS user_email, u.role
        FROM audit_logs al
        LEFT JOIN users u ON u.id = al.user_id
        WHERE al.college_id = :college_id
          {where_sql}
        ORDER BY al.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM audit_logs al
        WHERE al.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.get("/stats")
def audit_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id

    by_action = db.execute(text("""
        SELECT action, COUNT(*) AS count
        FROM audit_logs WHERE college_id = :college_id
        GROUP BY action ORDER BY count DESC
    """), {"college_id": college_id}).fetchall()

    by_table = db.execute(text("""
        SELECT table_name, COUNT(*) AS count
        FROM audit_logs WHERE college_id = :college_id
        GROUP BY table_name ORDER BY count DESC LIMIT 10
    """), {"college_id": college_id}).fetchall()

    recent_activity = db.execute(text("""
        SELECT
            TO_CHAR(created_at, 'YYYY-MM-DD') AS day,
            COUNT(*) AS events
        FROM audit_logs
        WHERE college_id = :college_id
          AND created_at >= NOW() - INTERVAL '30 days'
        GROUP BY day ORDER BY day
    """), {"college_id": college_id}).fetchall()

    return {
        "by_action": [dict(r._mapping) for r in by_action],
        "by_table": [dict(r._mapping) for r in by_table],
        "recent_activity": [dict(r._mapping) for r in recent_activity],
    }


