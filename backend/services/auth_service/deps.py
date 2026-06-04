"""
FastAPI dependency injection for authentication and authorization.
Used by ALL services via import.
"""
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import settings
from backend.core.security import verify_token, hash_api_key
from backend.core.redis_client import session_cache, user_cache

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        username: str,
        email: str,
        roles: list[str],
        permissions: set[str],
    ):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.username = username
        self.email = email
        self.roles = roles
        self.permissions = permissions

    def has_role(self, *roles: str) -> bool:
        return bool(set(self.roles) & set(roles))

    def can(self, resource: str, action: str) -> bool:
        return f"{resource}:{action}" in self.permissions or "super_admin" in self.roles

    def require(self, resource: str, action: str) -> None:
        if not self.can(resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {action} on {resource}",
            )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> CurrentUser:
    token_str: str | None = None

    # 1. Try Bearer token
    if credentials:
        token_str = credentials.credentials

    # 2. Try API key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await _authenticate_api_key(api_key)

    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate JWT
    payload = verify_token(token_str)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check session is still valid (not logged out)
    session_key = f"session:{payload.get('jti', token_str[:16])}"
    if await session_cache.exists(session_key):
        # Session was invalidated (logout)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been invalidated",
        )

    user = CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        tenant_id=uuid.UUID(payload["tenant_id"]),
        username=payload.get("username", ""),
        email=payload.get("email", ""),
        roles=payload.get("roles", []),
        permissions=set(payload.get("permissions", [])),
    )
    request.state.user_id = str(user.user_id)
    request.state.tenant_id = str(user.tenant_id)
    request.state.roles = user.roles
    return user


async def _authenticate_api_key(api_key: str) -> CurrentUser:
    from backend.core.database import get_db_context
    from backend.shared.models.user import APIKey

    key_hash = hash_api_key(api_key)
    cached = await user_cache.get(f"apikey:{key_hash}")
    if cached:
        return CurrentUser(**cached)

    async with get_db_context() as db:
        from sqlalchemy import select
        from datetime import datetime, timezone

        result = await db.execute(
            select(APIKey).where(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True,
            )
        )
        key_obj = result.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        if key_obj.expires_at and key_obj.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

        # Update last_used
        from datetime import datetime, timezone
        key_obj.last_used_at = datetime.now(timezone.utc)

        return CurrentUser(
            user_id=key_obj.user_id,
            tenant_id=key_obj.tenant_id,
            username=f"apikey:{key_obj.name}",
            email="",
            roles=["api_service"],
            permissions=set(key_obj.scopes if hasattr(key_obj, 'scopes') else []),
        )


# ── Convenience dependency aliases ────────────────────────────────────────────

AuthRequired = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: str):
    async def checker(user: AuthRequired) -> CurrentUser:
        if not user.has_role(*roles, "super_admin", "tenant_admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {', '.join(roles)}",
            )
        return user
    return Depends(checker)


def require_permission(resource: str, action: str):
    async def checker(user: AuthRequired) -> CurrentUser:
        user.require(resource, action)
        return user
    return Depends(checker)
