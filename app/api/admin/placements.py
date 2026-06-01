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


