"""
Admin — Reports & Settings API
Tables: reports, colleges, naac_criteria_data
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────────────────
reports_router = APIRouter(prefix="/admin/reports", tags=["Admin – Reports"])


@reports_router.get("")
def list_reports(
    report_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if report_type:
        where.append("r.report_type = :report_type")
        params["report_type"] = report_type
    if status:
        where.append("r.status = :status")
        params["status"] = status

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            r.id, r.title, r.report_type, r.format, r.status,
            r.file_path, r.file_size_kb, r.parameters,
            r.validation_passed, r.error_message,
            r.created_at, r.completed_at,
            u.full_name AS generated_by_name
        FROM reports r
        JOIN users u ON u.id = r.generated_by
        WHERE r.college_id = :college_id
          {where_sql}
        ORDER BY r.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM reports r WHERE r.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@reports_router.post("")
def create_report(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Queue a report for generation."""
    college_id = current_user.college_id
    row = db.execute(text("""
        INSERT INTO reports
            (college_id, generated_by, title, report_type, format, parameters, status)
        VALUES
            (:college_id, :user_id, :title, :report_type, :format, :parameters, 'queued')
        RETURNING id
    """), {
        "college_id": college_id,
        "user_id": current_user.id,
        "title": body["title"],
        "report_type": body["report_type"],
        "format": body.get("format", "pdf"),
        "parameters": body.get("parameters", "{}"),
    }).fetchone()
    db.commit()
    return {"id": row.id, "status": "queued", "success": True}


# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
settings_router = APIRouter(prefix="/admin/settings", tags=["Admin – Settings"])


@settings_router.get("/college")
def get_college_settings(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    row = db.execute(text("""
        SELECT
            id, name, short_name, code, address, city, state, pincode,
            phone, email, website, logo_url,
            accreditation_type, naac_grade, naac_cgpa, naac_valid_until,
            nba_programs, university_name, university_code,
            is_autonomous, subscription_plan, settings, onboarded_at
        FROM colleges WHERE id = :college_id
    """), {"college_id": college_id}).fetchone()
    return dict(row._mapping) if row else {}


@settings_router.patch("/college")
def update_college_settings(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    allowed = {
        "name", "short_name", "address", "city", "state", "pincode",
        "phone", "email", "website", "logo_url",
        "naac_grade", "naac_cgpa", "naac_valid_until", "university_name",
        "is_autonomous", "settings",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return {"success": True, "changed": 0}
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = college_id
    db.execute(text(f"UPDATE colleges SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
    db.commit()
    return {"success": True, "changed": len(updates) - 1}


@settings_router.get("/naac")
def get_naac_data(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    rows = db.execute(text("""
        SELECT
            id, cycle, criterion, metric_name, value_text, value_numeric,
            value_json, is_verified, notes, computed_at, updated_at
        FROM naac_criteria_data
        WHERE college_id = :college_id
        ORDER BY cycle DESC, criterion
    """), {"college_id": college_id}).fetchall()
    return [dict(r._mapping) for r in rows]


