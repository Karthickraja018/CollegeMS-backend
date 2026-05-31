"""
Admin — Placements Management API
Tables: placement_drives, placement_applications, placement_offers
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/placements", tags=["Admin – Placements"])


@router.get("/drives")
def list_drives(
    status: Optional[str] = None,
    drive_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if status:
        where.append("pd.status = :status")
        params["status"] = status
    if drive_type:
        where.append("pd.drive_type = :drive_type")
        params["drive_type"] = drive_type
    if search:
        where.append("pd.company_name ILIKE :search")
        params["search"] = f"%{search}%"

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            pd.id, pd.company_name, pd.company_logo_url, pd.industry,
            pd.job_role, pd.ctc_lpa, pd.drive_type, pd.drive_date,
            pd.registration_deadline, pd.status, pd.min_cgpa, pd.max_backlogs,
            pd.eligible_batches, pd.rounds_count, pd.created_at,
            COUNT(pa.id)                                              AS total_applications,
            COUNT(pa.id) FILTER (WHERE pa.status = 'selected')        AS selected_count,
            COUNT(pa.id) FILTER (WHERE pa.status = 'shortlisted')     AS shortlisted_count
        FROM placement_drives pd
        LEFT JOIN placement_applications pa ON pa.drive_id = pd.id
        WHERE pd.college_id = :college_id
          {where_sql}
        GROUP BY pd.id
        ORDER BY pd.drive_date DESC NULLS LAST, pd.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM placement_drives pd
        WHERE pd.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.post("/drives")
def create_drive(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    row = db.execute(text("""
        INSERT INTO placement_drives
            (college_id, company_name, company_logo_url, industry, job_role,
             job_description, job_location, ctc_lpa, ctc_breakup, drive_type,
             drive_date, registration_deadline, eligible_programs, eligible_batches,
             min_cgpa, max_backlogs, eligibility_criteria, status, rounds_count)
        VALUES
            (:college_id, :company_name, :company_logo_url, :industry, :job_role,
             :job_description, :job_location, :ctc_lpa, :ctc_breakup, :drive_type,
             :drive_date, :registration_deadline, :eligible_programs, :eligible_batches,
             :min_cgpa, :max_backlogs, :eligibility_criteria, :status, :rounds_count)
        RETURNING id
    """), {
        "college_id": college_id,
        "company_name": body["company_name"],
        "company_logo_url": body.get("company_logo_url"),
        "industry": body.get("industry"),
        "job_role": body["job_role"],
        "job_description": body.get("job_description"),
        "job_location": body.get("job_location"),
        "ctc_lpa": body.get("ctc_lpa"),
        "ctc_breakup": body.get("ctc_breakup"),
        "drive_type": body.get("drive_type", "on_campus"),
        "drive_date": body.get("drive_date"),
        "registration_deadline": body.get("registration_deadline"),
        "eligible_programs": body.get("eligible_programs"),
        "eligible_batches": body.get("eligible_batches"),
        "min_cgpa": body.get("min_cgpa"),
        "max_backlogs": body.get("max_backlogs", 0),
        "eligibility_criteria": body.get("eligibility_criteria"),
        "status": body.get("status", "upcoming"),
        "rounds_count": body.get("rounds_count", 3),
    }).fetchone()
    db.commit()
    return {"id": row.id, "success": True}


@router.patch("/drives/{drive_id}")
def update_drive(
    drive_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    allowed = {"status", "drive_date", "registration_deadline", "ctc_lpa",
               "min_cgpa", "max_backlogs", "eligibility_criteria", "rounds_count"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = drive_id
    db.execute(text(f"UPDATE placement_drives SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
    db.commit()
    return {"success": True}


@router.delete("/drives/{drive_id}")
def delete_drive(
    drive_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    db.execute(text("DELETE FROM placement_drives WHERE id = :id"), {"id": drive_id})
    db.commit()
    return {"success": True}


@router.get("/applications")
def list_applications(
    drive_id: Optional[int] = None,
    student_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if drive_id:
        where.append("pa.drive_id = :drive_id")
        params["drive_id"] = drive_id
    if student_id:
        where.append("pa.student_id = :student_id")
        params["student_id"] = student_id
    if status:
        where.append("pa.status = :status")
        params["status"] = status

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            pa.id, pa.status, pa.round_cleared, pa.applied_at, pa.updated_at, pa.notes,
            st.name AS student_name, st.roll_number,
            d.name AS department_name,
            p.code AS program_code,
            st.batch,
            pd.company_name, pd.job_role, pd.ctc_lpa,
            po.ctc_offered, po.role_title, po.is_accepted
        FROM placement_applications pa
        JOIN students st ON st.id = pa.student_id
        JOIN departments d ON d.id = st.department_id
        JOIN programs p ON p.id = st.program_id
        JOIN placement_drives pd ON pd.id = pa.drive_id
        LEFT JOIN placement_offers po ON po.application_id = pa.id
        WHERE pd.college_id = :college_id
          {where_sql}
        ORDER BY pa.updated_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM placement_applications pa
        JOIN placement_drives pd ON pd.id = pa.drive_id
        WHERE pd.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.patch("/applications/{app_id}/status")
def update_application_status(
    app_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    new_status = body.get("status")
    round_cleared = body.get("round_cleared")
    params: dict = {"id": app_id, "status": new_status, "updated_at": "NOW()"}
    set_parts = ["status = :status", "updated_at = NOW()"]
    if round_cleared is not None:
        set_parts.append("round_cleared = :round_cleared")
        params["round_cleared"] = round_cleared
    if body.get("notes"):
        set_parts.append("notes = :notes")
        params["notes"] = body["notes"]

    db.execute(text(f"UPDATE placement_applications SET {', '.join(set_parts)} WHERE id = :id"), params)
    db.commit()
    return {"success": True}


@router.get("/analytics")
def placement_analytics(
    academic_year: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    """Placement overview: offers, packages, department breakdown."""
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}
    ay_clause = ""
    if academic_year:
        ay_clause = "AND EXTRACT(YEAR FROM pd.drive_date) = :year"
        params["year"] = int(academic_year.split("-")[0])

    overview = db.execute(text(f"""
        SELECT
            COUNT(DISTINCT pd.id)                                              AS total_drives,
            COUNT(DISTINCT pa.student_id)
                FILTER (WHERE pa.status = 'selected')                          AS placed_students,
            ROUND(AVG(po.ctc_offered), 2)                                      AS avg_ctc,
            MAX(po.ctc_offered)                                                AS highest_ctc,
            MIN(po.ctc_offered)                                                AS lowest_ctc,
            COUNT(DISTINCT pd.company_name)                                    AS companies_visited
        FROM placement_drives pd
        LEFT JOIN placement_applications pa ON pa.drive_id = pd.id
        LEFT JOIN placement_offers po ON po.application_id = pa.id
        WHERE pd.college_id = :college_id
          {ay_clause}
    """), params).fetchone()

    by_dept = db.execute(text(f"""
        SELECT
            d.name AS department_name,
            d.code AS dept_code,
            COUNT(DISTINCT pa.student_id) FILTER (WHERE pa.status = 'selected') AS placed,
            ROUND(AVG(po.ctc_offered), 2)                                        AS avg_ctc,
            MAX(po.ctc_offered)                                                  AS highest_ctc
        FROM placement_applications pa
        JOIN placement_drives pd ON pd.id = pa.drive_id
        JOIN students st ON st.id = pa.student_id
        JOIN departments d ON d.id = st.department_id
        LEFT JOIN placement_offers po ON po.application_id = pa.id
        WHERE pd.college_id = :college_id
          {ay_clause}
        GROUP BY d.id, d.name, d.code
        ORDER BY placed DESC
    """), params).fetchall()

    ctc_distribution = db.execute(text(f"""
        SELECT
            CASE
                WHEN po.ctc_offered < 3  THEN '< 3 LPA'
                WHEN po.ctc_offered < 5  THEN '3-5 LPA'
                WHEN po.ctc_offered < 10 THEN '5-10 LPA'
                WHEN po.ctc_offered < 20 THEN '10-20 LPA'
                ELSE '20+ LPA'
            END AS range,
            COUNT(*) AS count
        FROM placement_offers po
        JOIN placement_applications pa ON pa.id = po.application_id
        JOIN placement_drives pd ON pd.id = pa.drive_id
        WHERE pd.college_id = :college_id
          {ay_clause}
        GROUP BY range
        ORDER BY MIN(po.ctc_offered)
    """), params).fetchall()

    return {
        "overview": dict(overview._mapping),
        "by_department": [dict(r._mapping) for r in by_dept],
        "ctc_distribution": [dict(r._mapping) for r in ctc_distribution],
    }


