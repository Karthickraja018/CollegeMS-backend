"""
FastAPI dependency for authentication and role-based access control.

Extended with:
- Role-specific convenience dependencies for all 4 roles
- DataScope injection for row-level filtering
- AI context dependency for the chat endpoint
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth_service import decode_token, get_user_by_id
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT from Authorization header."""
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        jti = payload.get("jti")
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if jti:
        from app.models.auth import RevokedToken
        from sqlalchemy import select
        result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_roles(*roles: UserRole):
    """Dependency factory: restrict endpoint to specific roles."""
    async def check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {[r.value for r in roles]}",
            )
        return current_user
    return check_role


# ── Convenience role dependencies ─────────────────────────────────────────────

require_admin = require_roles(UserRole.admin, UserRole.college_admin)
require_admin_or_principal = require_roles(UserRole.admin, UserRole.college_admin, UserRole.principal)
require_admin_principal_hod = require_roles(UserRole.admin, UserRole.college_admin, UserRole.principal, UserRole.hod)
require_principal = require_roles(UserRole.principal, UserRole.admin, UserRole.college_admin)
require_hod = require_roles(UserRole.hod, UserRole.admin, UserRole.college_admin)
require_faculty = require_roles(UserRole.faculty, UserRole.hod, UserRole.admin, UserRole.college_admin)

# Phase 2 alias — used by admin sub-modules
get_current_college_admin = require_roles(
    UserRole.admin, UserRole.college_admin, UserRole.principal
)


# ── DataScope dependency ───────────────────────────────────────────────────────

async def get_data_scope(current_user: User = Depends(get_current_user)):
    """
    Inject the resolved DataScope for the current user.
    Use this in analytics/intelligence endpoints for row-level filtering.
    """
    from app.roles import get_data_scope as _get_data_scope
    return _get_data_scope(current_user)


async def get_ai_context(current_user: User = Depends(get_current_user)):
    """
    Inject the AI context dict for the current user.
    Passed into AgentState so the LLM respects data scope.
    """
    from app.roles import get_ai_context_for_role
    return get_ai_context_for_role(current_user)
