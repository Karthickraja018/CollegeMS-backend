"""
Admin User Management API.
Full CRUD for all staff users: admin, principal, hod, faculty, staff.
Mapped to the 'users' table.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

_admin = require_roles(UserRole.admin)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "faculty"
    department_id: Optional[int] = None
    employee_id: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    employee_id: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    new_password: str


@router.get("")
async def list_users(
    role: Optional[str] = None,
    department_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all staff users with filtering, search, and pagination."""
    conditions = []
    params: dict = {"offset": (page - 1) * page_size, "limit": page_size}

    if role:
        conditions.append("u.role = :role")
        params["role"] = role
    if department_id:
        conditions.append("u.department_id = :dept_id")
        params["dept_id"] = department_id
    if is_active is not None:
        conditions.append("u.is_active = :is_active")
        params["is_active"] = is_active
    if search:
        conditions.append("(u.full_name ILIKE :search OR u.email ILIKE :search OR u.employee_id ILIKE :search)")
        params["search"] = f"%{search}%"

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    r = await db.execute(
        text(f"""
            SELECT
                u.id, u.email, u.full_name, u.employee_id, u.role,
                u.department_id, u.phone, u.designation, u.qualification,
                u.experience_years, u.is_active, u.last_login, u.created_at,
                d.name AS department_name,
                d.code AS department_code
            FROM users u
            LEFT JOIN departments d ON d.id = u.department_id
            {where}
            ORDER BY u.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = r.fetchall()
    data = [dict(zip(r.keys(), row)) for row in rows]

    # Total count
    count_params = {k: v for k, v in params.items() if k not in ("offset", "limit")}
    count_r = await db.execute(
        text(f"SELECT COUNT(*) FROM users u LEFT JOIN departments d ON d.id = u.department_id {where}"),
        count_params,
    )
    total = count_r.scalar() or 0

    return {"data": data, "total": total, "page": page, "page_size": page_size}


@router.get("/{user_id}")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        text("""
            SELECT
                u.id, u.email, u.full_name, u.employee_id, u.role,
                u.department_id, u.phone, u.designation, u.qualification,
                u.experience_years, u.is_active, u.last_login,
                u.created_at, u.updated_at,
                d.name AS department_name
            FROM users u
            LEFT JOIN departments d ON d.id = u.department_id
            WHERE u.id = :id
        """),
        {"id": user_id},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(zip(r.keys(), row))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    # Check email uniqueness
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": body.email}
    )
    if existing.scalar():
        raise HTTPException(status_code=409, detail="Email already registered")

    r = await db.execute(
        text("""
            INSERT INTO users
                (college_id, email, full_name, password_hash, role, department_id,
                 employee_id, phone, designation, qualification, experience_years)
            VALUES
                (1, :email, :full_name, :password_hash, :role, :department_id,
                 :employee_id, :phone, :designation, :qualification, :experience_years)
            RETURNING id, email, full_name, role, is_active
        """),
        {
            **body.model_dump(exclude={"password"}),
            "password_hash": hash_password(body.password),
        },
    )
    await db.commit()
    row = r.fetchone()
    return dict(zip(r.keys(), row))


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k}=:{k}" for k in updates)
    updates["id"] = user_id
    updates["updated_at"] = "NOW()"

    r = await db.execute(
        text(f"""
            UPDATE users SET {set_clause}, updated_at=NOW()
            WHERE id=:id
            RETURNING id, email, full_name, role, is_active
        """),
        updates,
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(zip(r.keys(), row))


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    body: PasswordReset,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    r = await db.execute(
        text("""
            UPDATE users SET password_hash=:pw, updated_at=NOW()
            WHERE id=:id RETURNING id, email
        """),
        {"pw": hash_password(body.new_password), "id": user_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Password reset successfully", "user_id": row[0]}


@router.patch("/{user_id}/toggle")
async def toggle_user_status(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    """Activate or deactivate a user."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    r = await db.execute(
        text("""
            UPDATE users SET is_active = NOT is_active, updated_at = NOW()
            WHERE id = :id RETURNING id, full_name, is_active
        """),
        {"id": user_id},
    )
    await db.commit()
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(zip(r.keys(), row))


@router.get("/{user_id}/activity")
async def get_user_activity(
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return audit log entries for a specific user."""
    r = await db.execute(
        text("""
            SELECT id, table_name, action, record_id, created_at, ip_address
            FROM audit_logs
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"user_id": user_id, "limit": limit},
    )
    rows = r.fetchall()
    return [dict(zip(r.keys(), row)) for row in rows]
