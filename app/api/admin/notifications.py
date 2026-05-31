"""
Admin — Notifications API
Table: notifications
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/notifications", tags=["Admin – Notifications"])


@router.get("")
def list_notifications(
    user_id: Optional[int] = None,
    type: Optional[str] = None,
    is_read: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if user_id:
        where.append("n.user_id = :user_id")
        params["user_id"] = user_id
    if type:
        where.append("n.type = :type")
        params["type"] = type
    if is_read is not None:
        where.append("n.is_read = :is_read")
        params["is_read"] = is_read

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            n.id, n.title, n.body, n.type, n.is_read, n.action_url,
            n.metadata, n.created_at,
            u.full_name AS recipient_name, u.email AS recipient_email, u.role
        FROM notifications n
        JOIN users u ON u.id = n.user_id
        WHERE n.college_id = :college_id
          {where_sql}
        ORDER BY n.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM notifications n
        WHERE n.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    count = db.execute(text("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = :user_id AND is_read = FALSE
    """), {"user_id": current_user.id}).scalar()
    return {"unread_count": count}


@router.post("/broadcast")
def broadcast_notification(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """
    Send a notification to all users matching role / department filters.
    body: { title, body, type, role?, department_id?, action_url? }
    """
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}
    where = ["u.college_id = :college_id", "u.is_active = TRUE"]

    if body.get("role"):
        where.append("u.role = :role")
        params["role"] = body["role"]
    if body.get("department_id"):
        where.append("u.department_id = :department_id")
        params["department_id"] = body["department_id"]

    users = db.execute(text(f"""
        SELECT id FROM users u WHERE {' AND '.join(where)}
    """), params).fetchall()

    for user in users:
        db.execute(text("""
            INSERT INTO notifications (user_id, college_id, title, body, type, action_url)
            VALUES (:user_id, :college_id, :title, :body, :type, :action_url)
        """), {
            "user_id": user.id,
            "college_id": college_id,
            "title": body["title"],
            "body": body["body"],
            "type": body.get("type", "general"),
            "action_url": body.get("action_url"),
        })
    db.commit()
    return {"success": True, "sent_to": len(users)}


@router.patch("/{notif_id}/read")
def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    db.execute(text("UPDATE notifications SET is_read = TRUE WHERE id = :id"), {"id": notif_id})
    db.commit()
    return {"success": True}


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    db.execute(text("""
        UPDATE notifications SET is_read = TRUE
        WHERE user_id = :user_id AND is_read = FALSE
    """), {"user_id": current_user.id})
    db.commit()
    return {"success": True}


