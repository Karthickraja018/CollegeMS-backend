"""
Role capabilities and data scope resolvers.

Usage:
    scope = get_data_scope(user)
    scope.department_id  # None for admin/principal, user.department_id for HOD
    scope.is_institution_wide  # True for admin/principal
    scope.student_filter  # 'all' | 'department' | 'assigned'
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from app.models.user import User, UserRole


@dataclass
class DataScope:
    """Resolved data scope for a user — used in query filtering."""
    role: str
    department_id: Optional[int]       # None = institution-wide
    is_institution_wide: bool          # True for admin/principal
    is_dept_scoped: bool               # True for HOD
    is_assignment_scoped: bool         # True for faculty
    student_filter: str                # 'all' | 'department' | 'assigned'
    can_view_all_depts: bool
    can_generate_reports: bool
    can_manage_users: bool
    can_sync_data: bool


def get_data_scope(user: User) -> DataScope:
    """
    Resolve the data access scope for a user based on their role.
    This is the single source of truth for what data a user can access.
    """
    role = user.role

    if role in (UserRole.admin, UserRole.college_admin):
        return DataScope(
            role=role.value,
            department_id=None,
            is_institution_wide=True,
            is_dept_scoped=False,
            is_assignment_scoped=False,
            student_filter="all",
            can_view_all_depts=True,
            can_generate_reports=True,
            can_manage_users=True,
            can_sync_data=True,
        )

    elif role == UserRole.principal:
        return DataScope(
            role=role.value,
            department_id=None,
            is_institution_wide=True,
            is_dept_scoped=False,
            is_assignment_scoped=False,
            student_filter="all",
            can_view_all_depts=True,
            can_generate_reports=True,
            can_manage_users=False,
            can_sync_data=False,
        )

    elif role == UserRole.hod:
        return DataScope(
            role=role.value,
            department_id=user.department_id,
            is_institution_wide=False,
            is_dept_scoped=True,
            is_assignment_scoped=False,
            student_filter="department",
            can_view_all_depts=False,
            can_generate_reports=True,
            can_manage_users=False,
            can_sync_data=False,
        )

    elif role == UserRole.faculty:
        return DataScope(
            role=role.value,
            department_id=user.department_id,
            is_institution_wide=False,
            is_dept_scoped=False,
            is_assignment_scoped=True,
            student_filter="assigned",
            can_view_all_depts=False,
            can_generate_reports=False,
            can_manage_users=False,
            can_sync_data=False,
        )

    else:
        # staff, student — no access
        return DataScope(
            role=role.value if role else "unknown",
            department_id=None,
            is_institution_wide=False,
            is_dept_scoped=False,
            is_assignment_scoped=False,
            student_filter="none",
            can_view_all_depts=False,
            can_generate_reports=False,
            can_manage_users=False,
            can_sync_data=False,
        )


def get_ai_context_for_role(user: User) -> dict:
    """
    Build the AI context dict injected into AgentState.
    Controls what the LLM can access during query generation.
    """
    scope = get_data_scope(user)
    return {
        "user_id": user.id,
        "user_role": user.role.value,
        "user_name": user.full_name,
        "department_id": scope.department_id,
        "is_institution_wide": scope.is_institution_wide,
        "student_filter": scope.student_filter,
        "can_view_all_depts": scope.can_view_all_depts,
        "department_filter_sql": (
            f"AND s.department_id = {scope.department_id}"
            if scope.department_id else ""
        ),
        "student_filter_sql": (
            "AND s.department_id = (SELECT department_id FROM users WHERE id = :user_id)"
            if scope.student_filter == "department"
            else "AND s.id IN (SELECT DISTINCT s2.id FROM students s2 JOIN faculty_subject_assignments fsa ON fsa.subject_id IN (SELECT subject_id FROM faculty_subject_assignments WHERE user_id = :user_id) JOIN marks m ON m.student_id = s2.id)"
            if scope.student_filter == "assigned"
            else ""
        ),
    }
