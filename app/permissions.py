"""
Permission matrix for the Academic Intelligence Platform.

Design:
- Permissions are named capabilities (strings).
- Each role is mapped to a set of capabilities.
- Enforcement happens at the API layer via deps.py and access_policies.py.
- Never rely on frontend visibility alone.
"""
from __future__ import annotations
from typing import Set, Dict, FrozenSet
from app.models.user import UserRole

# ── Permission Names ──────────────────────────────────────────────────────────

class Perm:
    # Dashboard
    VIEW_ADMIN_DASHBOARD        = "view_admin_dashboard"
    VIEW_PRINCIPAL_DASHBOARD    = "view_principal_dashboard"
    VIEW_HOD_DASHBOARD          = "view_hod_dashboard"
    VIEW_FACULTY_DASHBOARD      = "view_faculty_dashboard"

    # Data scope
    VIEW_ALL_DEPARTMENTS        = "view_all_departments"
    VIEW_OWN_DEPARTMENT         = "view_own_department"
    VIEW_ALL_STUDENTS           = "view_all_students"
    VIEW_DEPT_STUDENTS          = "view_dept_students"
    VIEW_ASSIGNED_STUDENTS      = "view_assigned_students"

    # Intelligence
    VIEW_STUDENT_INTELLIGENCE   = "view_student_intelligence"
    VIEW_DEPT_INTELLIGENCE      = "view_dept_intelligence"
    VIEW_INSTITUTIONAL_INTEL    = "view_institutional_intel"

    # Analytics
    VIEW_ANALYTICS              = "view_analytics"
    VIEW_DEPT_ANALYTICS         = "view_dept_analytics"
    VIEW_INSTITUTIONAL_ANALYTICS = "view_institutional_analytics"

    # Reports
    VIEW_REPORTS                = "view_reports"
    GENERATE_REPORTS            = "generate_reports"

    # AI
    USE_AI_COPILOT              = "use_ai_copilot"
    TRIGGER_AI_SCAN             = "trigger_ai_scan"
    VIEW_AI_OPS                 = "view_ai_ops"

    # Admin
    MANAGE_USERS                = "manage_users"
    MANAGE_ACADEMIC_SETUP       = "manage_academic_setup"
    SYNC_DATA                   = "sync_data"
    VIEW_AUDIT_LOGS             = "view_audit_logs"


# ── Role → Permission Matrix ──────────────────────────────────────────────────

_ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    UserRole.admin: frozenset({
        Perm.VIEW_ADMIN_DASHBOARD,
        Perm.VIEW_ALL_DEPARTMENTS,
        Perm.VIEW_ALL_STUDENTS,
        Perm.VIEW_STUDENT_INTELLIGENCE,
        Perm.VIEW_DEPT_INTELLIGENCE,
        Perm.VIEW_INSTITUTIONAL_INTEL,
        Perm.VIEW_ANALYTICS,
        Perm.VIEW_DEPT_ANALYTICS,
        Perm.VIEW_INSTITUTIONAL_ANALYTICS,
        Perm.VIEW_REPORTS,
        Perm.GENERATE_REPORTS,
        Perm.USE_AI_COPILOT,
        Perm.TRIGGER_AI_SCAN,
        Perm.VIEW_AI_OPS,
        Perm.MANAGE_USERS,
        Perm.MANAGE_ACADEMIC_SETUP,
        Perm.SYNC_DATA,
        Perm.VIEW_AUDIT_LOGS,
    }),

    UserRole.college_admin: frozenset({
        Perm.VIEW_ADMIN_DASHBOARD,
        Perm.VIEW_ALL_DEPARTMENTS,
        Perm.VIEW_ALL_STUDENTS,
        Perm.VIEW_STUDENT_INTELLIGENCE,
        Perm.VIEW_DEPT_INTELLIGENCE,
        Perm.VIEW_INSTITUTIONAL_INTEL,
        Perm.VIEW_ANALYTICS,
        Perm.VIEW_DEPT_ANALYTICS,
        Perm.VIEW_INSTITUTIONAL_ANALYTICS,
        Perm.VIEW_REPORTS,
        Perm.GENERATE_REPORTS,
        Perm.USE_AI_COPILOT,
        Perm.TRIGGER_AI_SCAN,
        Perm.VIEW_AI_OPS,
        Perm.MANAGE_USERS,
        Perm.MANAGE_ACADEMIC_SETUP,
        Perm.SYNC_DATA,
        Perm.VIEW_AUDIT_LOGS,
    }),

    UserRole.principal: frozenset({
        Perm.VIEW_PRINCIPAL_DASHBOARD,
        Perm.VIEW_ALL_DEPARTMENTS,
        Perm.VIEW_ALL_STUDENTS,
        Perm.VIEW_STUDENT_INTELLIGENCE,
        Perm.VIEW_DEPT_INTELLIGENCE,
        Perm.VIEW_INSTITUTIONAL_INTEL,
        Perm.VIEW_ANALYTICS,
        Perm.VIEW_DEPT_ANALYTICS,
        Perm.VIEW_INSTITUTIONAL_ANALYTICS,
        Perm.VIEW_REPORTS,
        Perm.GENERATE_REPORTS,
        Perm.USE_AI_COPILOT,
        # Read-only: no manage_users, no manage_academic_setup, no sync_data
    }),

    UserRole.hod: frozenset({
        Perm.VIEW_HOD_DASHBOARD,
        Perm.VIEW_OWN_DEPARTMENT,
        Perm.VIEW_DEPT_STUDENTS,
        Perm.VIEW_STUDENT_INTELLIGENCE,
        Perm.VIEW_DEPT_INTELLIGENCE,
        Perm.VIEW_ANALYTICS,
        Perm.VIEW_DEPT_ANALYTICS,
        Perm.VIEW_REPORTS,
        Perm.GENERATE_REPORTS,
        Perm.USE_AI_COPILOT,
        # Cannot view other departments, cannot view institutional analytics
    }),

    UserRole.faculty: frozenset({
        Perm.VIEW_FACULTY_DASHBOARD,
        Perm.VIEW_ASSIGNED_STUDENTS,
        Perm.VIEW_STUDENT_INTELLIGENCE,
        Perm.VIEW_ANALYTICS,
        Perm.USE_AI_COPILOT,
        # Strictly scoped to assigned students/subjects
    }),

    UserRole.staff: frozenset(),   # Inactive in this platform
    UserRole.student: frozenset(), # Inactive in this platform
}


def get_permissions(role: UserRole) -> FrozenSet[str]:
    """Return the permission set for a given role."""
    return _ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: UserRole, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in get_permissions(role)


def require_permission(role: UserRole, permission: str) -> None:
    """Raise ValueError if role lacks permission. Use in service layer."""
    if not has_permission(role, permission):
        raise PermissionError(
            f"Role '{role.value}' does not have permission '{permission}'"
        )
