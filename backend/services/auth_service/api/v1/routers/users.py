import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import hash_password
from backend.shared.models.user import User, Role, UserRole
from backend.services.auth_service.deps import AuthRequired, require_roles

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    roles: list[str] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_locked: bool
    mfa_enabled: bool
    roles: list[str]
    last_login_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[UserResponse])
async def list_users(
    user: AuthRequired,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    user.require("users", "read")
    query = select(User).where(User.tenant_id == user.tenant_id)
    if search:
        query = query.where(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    user_list = []
    for u in users:
        roles = await _get_user_roles(u.id, db)
        user_list.append(UserResponse(
            id=u.id, username=u.username, email=u.email or "",
            full_name=u.full_name, is_active=u.is_active, is_locked=u.is_locked,
            mfa_enabled=u.mfa_enabled, roles=roles,
            last_login_at=u.last_login_at, created_at=u.created_at,
        ))
    return user_list


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("users", "write")

    # Check uniqueness
    existing = await db.execute(
        select(User).where(
            User.tenant_id == current_user.tenant_id,
            User.username == body.username,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Username '{body.username}' already exists")

    new_user = User(
        tenant_id=current_user.tenant_id,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(new_user)
    await db.flush()  # get the ID

    # Assign roles
    if body.roles:
        role_result = await db.execute(
            select(Role).where(
                Role.tenant_id == current_user.tenant_id,
                Role.name.in_(body.roles),
            )
        )
        for role in role_result.scalars().all():
            db.add(UserRole(
                user_id=new_user.id,
                role_id=role.id,
                granted_by=current_user.user_id,
                granted_at=datetime.now(timezone.utc),
            ))

    await db.commit()
    return UserResponse(
        id=new_user.id, username=new_user.username, email=new_user.email or "",
        full_name=new_user.full_name, is_active=new_user.is_active,
        is_locked=new_user.is_locked, mfa_enabled=new_user.mfa_enabled,
        roles=body.roles, last_login_at=None, created_at=new_user.created_at,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("users", "read")
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    roles = await _get_user_roles(db_user.id, db)
    return UserResponse(
        id=db_user.id, username=db_user.username, email=db_user.email or "",
        full_name=db_user.full_name, is_active=db_user.is_active,
        is_locked=db_user.is_locked, mfa_enabled=db_user.mfa_enabled,
        roles=roles, last_login_at=db_user.last_login_at, created_at=db_user.created_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("users", "write")
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(db_user, field, value)

    await db.commit()
    roles = await _get_user_roles(db_user.id, db)
    return UserResponse(
        id=db_user.id, username=db_user.username, email=db_user.email or "",
        full_name=db_user.full_name, is_active=db_user.is_active,
        is_locked=db_user.is_locked, mfa_enabled=db_user.mfa_enabled,
        roles=roles, last_login_at=db_user.last_login_at, created_at=db_user.created_at,
    )


@router.post("/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
async def unlock_user(
    user_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("users", "write")
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.is_locked = False
    db_user.failed_attempts = 0
    await db.commit()


async def _get_user_roles(user_id: uuid.UUID, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [row.name for row in result.all()]
