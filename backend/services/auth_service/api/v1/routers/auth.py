import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import (
    verify_password, hash_password,
    create_access_token, create_refresh_token,
    verify_token, generate_secure_token,
)
from backend.core.redis_client import session_cache, user_cache
from backend.shared.models.user import User, Role, UserRole, Permission, RolePermission
from backend.services.auth_service.deps import AuthRequired, get_current_user

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_code: str
    mfa_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    username: str
    tenant_id: str
    roles: list[str]
    mfa_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class MFASetupResponse(BaseModel):
    secret: str
    qr_uri: str
    backup_codes: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_user_permissions(user_id: uuid.UUID, db: AsyncSession) -> list[str]:
    """Fetch all permissions for a user via their roles."""
    result = await db.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return [f"{row.resource}:{row.action}" for row in result.all()]


async def _get_user_roles(user_id: uuid.UUID, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return [row.name for row in result.all()]


async def _get_tenant_by_code(code: str, db: AsyncSession):
    from backend.shared.models.tenant import Tenant
    result = await db.execute(
        select(Tenant).where(Tenant.code == code, Tenant.is_active == True)
    )
    return result.scalar_one_or_none()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    # 1. Resolve tenant
    tenant = await _get_tenant_by_code(request.tenant_code, db)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # 2. Find user
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == request.username,
            User.is_active == True,
        )
    )
    user: User | None = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # 3. Check lockout
    if user.is_locked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is locked")

    # 4. Verify password
    if not verify_password(request.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= 5:
            user.is_locked = True
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # 5. MFA check
    if user.mfa_enabled:
        if not request.mfa_code:
            # Return indicator that MFA is required (no token yet)
            return TokenResponse(
                access_token="",
                refresh_token="",
                expires_in=0,
                user_id=str(user.id),
                username=user.username,
                tenant_id=str(tenant.id),
                roles=[],
                mfa_required=True,
            )
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(request.mfa_code, valid_window=1):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    # 6. Build token payload
    roles = await _get_user_roles(user.id, db)
    permissions = await _get_user_permissions(user.id, db)
    jti = generate_secure_token(16)

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(tenant.id),
        "username": user.username,
        "email": user.email or "",
        "roles": roles,
        "permissions": permissions,
        "jti": jti,
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id), "jti": jti, "tenant_id": str(tenant.id)})

    # 7. Update last login
    user.last_login_at = datetime.now(timezone.utc)
    user.failed_attempts = 0
    await db.commit()

    from backend.core.config import settings
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        username=user.username,
        tenant_id=str(tenant.id),
        roles=roles,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = verify_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = uuid.UUID(payload["sub"])
    tenant_id = uuid.UUID(payload["tenant_id"])

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user: User | None = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    roles = await _get_user_roles(user.id, db)
    permissions = await _get_user_permissions(user.id, db)
    jti = generate_secure_token(16)

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(tenant_id),
        "username": user.username,
        "email": user.email or "",
        "roles": roles,
        "permissions": permissions,
        "jti": jti,
    }
    access_token = create_access_token(token_data)
    new_refresh = create_refresh_token({"sub": str(user.id), "jti": jti, "tenant_id": str(tenant_id)})

    from backend.core.config import settings
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        username=user.username,
        tenant_id=str(tenant_id),
        roles=roles,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: AuthRequired):
    # Invalidate the current session via Redis
    await session_cache.set(f"session:{user.user_id}", "invalidated", ttl=86400)


@router.get("/me")
async def get_me(user: AuthRequired):
    return {
        "user_id": str(user.user_id),
        "tenant_id": str(user.tenant_id),
        "username": user.username,
        "email": user.email,
        "roles": user.roles,
    }


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(user: AuthRequired, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user.user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    qr_uri = totp.provisioning_uri(name=db_user.email or db_user.username, issuer_name="AEAOP")

    # Store secret temporarily — confirmed on /mfa/verify
    await session_cache.set(f"mfa_setup:{user.user_id}", secret, ttl=600)

    backup_codes = [generate_secure_token(8) for _ in range(8)]
    return MFASetupResponse(secret=secret, qr_uri=qr_uri, backup_codes=backup_codes)


@router.post("/mfa/verify")
async def verify_mfa_setup(
    code: str, user: AuthRequired, db: AsyncSession = Depends(get_db)
):
    secret = await session_cache.get(f"mfa_setup:{user.user_id}")
    if not secret:
        raise HTTPException(status_code=400, detail="MFA setup session expired")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid MFA code")

    result = await db.execute(select(User).where(User.id == user.user_id))
    db_user = result.scalar_one_or_none()
    db_user.mfa_secret = secret
    db_user.mfa_enabled = True
    await db.commit()
    await session_cache.delete(f"mfa_setup:{user.user_id}")

    return {"message": "MFA enabled successfully"}
