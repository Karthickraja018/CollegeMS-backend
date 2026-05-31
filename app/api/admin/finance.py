"""
Admin — Finance Management API
Tables: fee_structures, fee_accounts, fee_transactions
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_current_college_admin
from typing import Optional

router = APIRouter(prefix="/admin/finance", tags=["Admin – Finance"])


# ─────────────────────── Fee Structures ─────────────────────────────────────

@router.get("/structures")
def list_fee_structures(
    program_id: Optional[int] = None,
    academic_year: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}
    where = []
    if program_id:
        where.append("fs.program_id = :program_id")
        params["program_id"] = program_id
    if academic_year:
        where.append("fs.academic_year = :academic_year")
        params["academic_year"] = academic_year

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            fs.id, fs.academic_year, fs.category, fs.description,
            fs.amount, fs.is_mandatory, fs.due_date, fs.created_at,
            p.name AS program_name, p.code AS program_code,
            d.name AS department_name
        FROM fee_structures fs
        JOIN programs p ON p.id = fs.program_id
        JOIN departments d ON d.id = p.department_id
        WHERE fs.college_id = :college_id
          {where_sql}
        ORDER BY fs.academic_year DESC, p.name, fs.category
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/structures")
def create_fee_structure(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    row = db.execute(text("""
        INSERT INTO fee_structures
            (college_id, program_id, academic_year, category, description, amount, is_mandatory, due_date)
        VALUES
            (:college_id, :program_id, :academic_year, :category, :description, :amount, :is_mandatory, :due_date)
        RETURNING id
    """), {
        "college_id": college_id,
        "program_id": body["program_id"],
        "academic_year": body["academic_year"],
        "category": body["category"],
        "description": body["description"],
        "amount": body["amount"],
        "is_mandatory": body.get("is_mandatory", True),
        "due_date": body.get("due_date"),
    }).fetchone()
    db.commit()
    return {"id": row.id, "success": True}


@router.patch("/structures/{fs_id}")
def update_fee_structure(
    fs_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    allowed = {"description", "amount", "is_mandatory", "due_date"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = fs_id
    db.execute(text(f"UPDATE fee_structures SET {set_clause} WHERE id = :id"), updates)
    db.commit()
    return {"success": True}


@router.delete("/structures/{fs_id}")
def delete_fee_structure(
    fs_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    db.execute(text("DELETE FROM fee_structures WHERE id = :id"), {"id": fs_id})
    db.commit()
    return {"success": True}


# ─────────────────────── Fee Accounts ───────────────────────────────────────

@router.get("/accounts")
def list_fee_accounts(
    status: Optional[str] = None,
    academic_year: Optional[str] = None,
    department_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if status:
        where.append("fa.status = :status")
        params["status"] = status
    if academic_year:
        where.append("fa.academic_year = :academic_year")
        params["academic_year"] = academic_year
    if department_id:
        where.append("d.id = :department_id")
        params["department_id"] = department_id
    if search:
        where.append("(st.name ILIKE :search OR st.roll_number ILIKE :search)")
        params["search"] = f"%{search}%"

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            fa.id, fa.academic_year, fa.total_due, fa.total_paid, fa.concession,
            fa.balance, fa.status, fa.due_date, fa.scholarship_ref, fa.remarks,
            st.id AS student_id, st.name AS student_name, st.roll_number,
            d.name AS department_name,
            p.code AS program_code
        FROM fee_accounts fa
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        JOIN programs p ON p.id = st.program_id
        WHERE d.college_id = :college_id
          {where_sql}
        ORDER BY fa.status DESC, fa.balance DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM fee_accounts fa
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.patch("/accounts/{account_id}")
def update_fee_account(
    account_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    allowed = {"status", "concession", "due_date", "scholarship_ref", "remarks"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")
    updates["updated_at"] = "NOW()"
    set_clause = ", ".join(
        f"{k} = NOW()" if v == "NOW()" else f"{k} = :{k}"
        for k, v in updates.items()
    )
    db.execute(text(f"UPDATE fee_accounts SET {set_clause} WHERE id = :id"),
               {k: v for k, v in updates.items() if v != "NOW()"} | {"id": account_id})
    db.commit()
    return {"success": True}


# ─────────────────────── Fee Transactions ───────────────────────────────────

@router.get("/transactions")
def list_transactions(
    fee_account_id: Optional[int] = None,
    student_id: Optional[int] = None,
    mode: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    offset = (page - 1) * page_size
    params: dict = {"college_id": college_id, "limit": page_size, "offset": offset}
    where = []

    if fee_account_id:
        where.append("ft.fee_account_id = :fee_account_id")
        params["fee_account_id"] = fee_account_id
    if student_id:
        where.append("fa.student_id = :student_id")
        params["student_id"] = student_id
    if mode:
        where.append("ft.mode = :mode")
        params["mode"] = mode
    if date_from:
        where.append("ft.paid_on >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("ft.paid_on <= :date_to")
        params["date_to"] = date_to

    where_sql = "AND " + " AND ".join(where) if where else ""

    rows = db.execute(text(f"""
        SELECT
            ft.id, ft.amount, ft.mode, ft.receipt_number, ft.paid_on,
            ft.transaction_ref, ft.bank_name, ft.notes, ft.created_at,
            fa.academic_year, fa.student_id,
            st.name AS student_name, st.roll_number,
            d.name AS department_name,
            u.full_name AS collected_by_name
        FROM fee_transactions ft
        JOIN fee_accounts fa ON fa.id = ft.fee_account_id
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        LEFT JOIN users u ON u.id = ft.collected_by
        WHERE d.college_id = :college_id
          {where_sql}
        ORDER BY ft.paid_on DESC, ft.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM fee_transactions ft
        JOIN fee_accounts fa ON fa.id = ft.fee_account_id
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id {where_sql}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {"data": [dict(r._mapping) for r in rows], "total": total}


@router.post("/transactions")
def record_payment(
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    row = db.execute(text("""
        INSERT INTO fee_transactions
            (fee_account_id, fee_structure_id, amount, mode, receipt_number,
             paid_on, transaction_ref, bank_name, collected_by, notes)
        VALUES
            (:fee_account_id, :fee_structure_id, :amount, :mode, :receipt_number,
             :paid_on, :transaction_ref, :bank_name, :collected_by, :notes)
        RETURNING id
    """), {
        "fee_account_id": body["fee_account_id"],
        "fee_structure_id": body.get("fee_structure_id"),
        "amount": body["amount"],
        "mode": body["mode"],
        "receipt_number": body["receipt_number"],
        "paid_on": body.get("paid_on"),
        "transaction_ref": body.get("transaction_ref"),
        "bank_name": body.get("bank_name"),
        "collected_by": current_user.id,
        "notes": body.get("notes"),
    }).fetchone()

    # Update fee_accounts total_paid
    db.execute(text("""
        UPDATE fee_accounts
        SET total_paid = total_paid + :amount,
            updated_at = NOW()
        WHERE id = :account_id
    """), {"amount": body["amount"], "account_id": body["fee_account_id"]})

    db.commit()
    return {"id": row.id, "success": True}


# ─────────────────────── Finance Dashboard ───────────────────────────────────

@router.get("/dashboard")
def finance_dashboard(
    academic_year: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    params: dict = {"college_id": college_id}
    ay_clause = "AND fa.academic_year = :academic_year" if academic_year else ""
    if academic_year:
        params["academic_year"] = academic_year

    summary = db.execute(text(f"""
        SELECT
            COUNT(*)                                                AS total_accounts,
            ROUND(SUM(fa.total_due), 2)                             AS total_due,
            ROUND(SUM(fa.total_paid), 2)                            AS total_collected,
            ROUND(SUM(fa.balance), 2)                               AS total_outstanding,
            ROUND(SUM(fa.concession), 2)                            AS total_concession,
            COUNT(*) FILTER (WHERE fa.status = 'paid')              AS paid_count,
            COUNT(*) FILTER (WHERE fa.status = 'overdue')           AS overdue_count,
            COUNT(*) FILTER (WHERE fa.status = 'partially_paid')    AS partial_count,
            COUNT(*) FILTER (WHERE fa.status = 'due')               AS due_count,
            COUNT(*) FILTER (WHERE fa.status = 'waived')            AS waived_count
        FROM fee_accounts fa
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          {ay_clause}
    """), params).fetchone()

    monthly = db.execute(text(f"""
        SELECT
            TO_CHAR(ft.paid_on, 'YYYY-MM') AS month,
            ROUND(SUM(ft.amount), 2)        AS collected,
            COUNT(*)                        AS transactions
        FROM fee_transactions ft
        JOIN fee_accounts fa ON fa.id = ft.fee_account_id
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          {ay_clause}
        GROUP BY TO_CHAR(ft.paid_on, 'YYYY-MM')
        ORDER BY month
    """), params).fetchall()

    by_mode = db.execute(text(f"""
        SELECT
            ft.mode,
            ROUND(SUM(ft.amount), 2) AS amount,
            COUNT(*)                 AS count
        FROM fee_transactions ft
        JOIN fee_accounts fa ON fa.id = ft.fee_account_id
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          {ay_clause}
        GROUP BY ft.mode
        ORDER BY amount DESC
    """), params).fetchall()

    by_dept = db.execute(text(f"""
        SELECT
            d.name AS department_name,
            d.code AS dept_code,
            ROUND(SUM(fa.total_due), 2)    AS total_due,
            ROUND(SUM(fa.total_paid), 2)   AS total_paid,
            ROUND(SUM(fa.balance), 2)      AS outstanding,
            COUNT(*) FILTER (WHERE fa.status = 'overdue') AS overdue_count
        FROM fee_accounts fa
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          {ay_clause}
        GROUP BY d.id, d.name, d.code
        ORDER BY outstanding DESC
    """), params).fetchall()

    return {
        "summary": dict(summary._mapping),
        "monthly_collection": [dict(r._mapping) for r in monthly],
        "by_payment_mode": [dict(r._mapping) for r in by_mode],
        "by_department": [dict(r._mapping) for r in by_dept],
    }


@router.get("/overdue")
def overdue_accounts(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_college_admin),
):
    college_id = current_user.college_id
    rows = db.execute(text("""
        SELECT
            st.name, st.roll_number, st.email,
            d.name AS department_name,
            fa.academic_year, fa.balance, fa.due_date, fa.status
        FROM fee_accounts fa
        JOIN students st ON st.id = fa.student_id
        JOIN departments d ON d.id = st.department_id
        WHERE d.college_id = :college_id
          AND fa.status IN ('due', 'overdue')
        ORDER BY fa.balance DESC
        LIMIT 100
    """), {"college_id": college_id}).fetchall()
    return [dict(r._mapping) for r in rows]


