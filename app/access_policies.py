"""
Access policy enforcement functions.

These are called from API endpoints and service layer to enforce
row-level access control beyond role-level checks.

All functions raise HTTPException(403) on violation.
Never expose raw data without calling the appropriate policy first.
"""
from __future__ import annotations
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.user import User, UserRole
from app.roles import get_data_scope


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def assert_institution_access(user: User) -> None:
    """Only admin and principal can access institution-wide data."""
    scope = get_data_scope(user)
    if not scope.is_institution_wide:
        raise _forbidden(
            f"Role '{user.role.value}' cannot access institution-wide data. "
            "Only Admin and Principal have institution-wide access."
        )


def assert_department_access(user: User, department_id: int) -> None:
    """
    Verify the user can access data for a given department.
    - Admin/Principal: can access any department
    - HOD: only their own department
    - Faculty: only their own department (for reference)
    """
    scope = get_data_scope(user)

    if scope.is_institution_wide:
        return  # Admin/Principal: no restriction

    if scope.department_id is None:
        raise _forbidden("User has no department assigned.")

    if scope.department_id != department_id:
        raise _forbidden(
            f"You do not have access to department ID {department_id}. "
            "HOD and Faculty can only access their assigned department."
        )


async def assert_student_access(
    user: User, student_id: int, db: AsyncSession
) -> None:
    """
    Verify the user can access data for a specific student.
    - Admin/Principal: any student
    - HOD: students in their department
    - Faculty: students in their assigned subjects
    """
    scope = get_data_scope(user)

    if scope.is_institution_wide:
        return  # No restriction

    if scope.is_dept_scoped:
        # HOD: student must be in same department
        r = await db.execute(
            text("SELECT department_id FROM students WHERE id = :sid"),
            {"sid": student_id},
        )
        row = r.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")
        if row[0] != scope.department_id:
            raise _forbidden(
                "You can only access students in your department."
            )
        return

    if scope.is_assignment_scoped:
        # Faculty: student must be enrolled in an assigned subject
        r = await db.execute(
            text("""
                SELECT 1
                FROM marks m
                JOIN faculty_subject_assignments fsa ON fsa.subject_id = m.subject_id
                WHERE fsa.user_id = :uid AND m.student_id = :sid
                LIMIT 1
            """),
            {"uid": user.id, "sid": student_id},
        )
        if not r.fetchone():
            raise _forbidden(
                "You can only access students enrolled in your assigned subjects."
            )
        return

    raise _forbidden("Insufficient permissions to access student data.")


def assert_can_generate_reports(user: User) -> None:
    """Admin, Principal, and HOD can generate reports."""
    scope = get_data_scope(user)
    if not scope.can_generate_reports:
        raise _forbidden("Your role does not have permission to generate reports.")


def assert_can_sync_data(user: User) -> None:
    """Only Admin can sync data."""
    scope = get_data_scope(user)
    if not scope.can_sync_data:
        raise _forbidden(
            "Only administrators can sync data. "
            "Contact your system administrator to import data."
        )


def assert_can_manage_users(user: User) -> None:
    """Only Admin can manage users."""
    scope = get_data_scope(user)
    if not scope.can_manage_users:
        raise _forbidden("Only administrators can manage user accounts.")


def get_department_filter_sql(user: User) -> tuple[str, dict]:
    """
    Return a SQL fragment and params dict for department-level filtering.
    Safe to embed in queries: WHERE <dept_clause>

    Returns:
        (sql_fragment, params)
        sql_fragment: e.g. "AND s.department_id = :scope_dept_id"
        params: {"scope_dept_id": 3} or {}
    """
    scope = get_data_scope(user)
    if scope.department_id is not None and not scope.is_institution_wide:
        return "AND s.department_id = :scope_dept_id", {"scope_dept_id": scope.department_id}
    return "", {}


async def get_student_id_filter_sql(user: User, db: AsyncSession) -> tuple[str, dict]:
    """
    Return a SQL fragment for faculty-level student filtering via assignments.
    Returns empty string + {} for admin/principal/hod.
    """
    scope = get_data_scope(user)

    if not scope.is_assignment_scoped:
        return "", {}

    # Get subjects assigned to this faculty
    r = await db.execute(
        text("""
            SELECT DISTINCT m.student_id
            FROM marks m
            JOIN faculty_subject_assignments fsa ON fsa.subject_id = m.subject_id
            WHERE fsa.user_id = :uid
        """),
        {"uid": user.id},
    )
    student_ids = [row[0] for row in r.fetchall()]

    if not student_ids:
        # Faculty has no assignments — return an impossible condition
        return "AND s.id = -1", {}

    placeholders = ", ".join(str(sid) for sid in student_ids)
    return f"AND s.id IN ({placeholders})", {}
