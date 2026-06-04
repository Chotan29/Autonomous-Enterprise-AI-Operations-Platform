import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.user import Role, Permission, RolePermission
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str] = []  # ["devices:read", "alerts:write"]


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    is_system: bool
    permissions: list[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[RoleResponse])
async def list_roles(current_user: AuthRequired, db: AsyncSession = Depends(get_db)):
    current_user.require("roles", "read")
    result = await db.execute(
        select(Role).where(Role.tenant_id == current_user.tenant_id)
    )
    roles = result.scalars().all()
    role_list = []
    for role in roles:
        perms = await _get_role_permissions(role.id, db)
        role_list.append(RoleResponse(
            id=role.id, name=role.name, description=role.description,
            is_system=role.is_system, permissions=perms,
        ))
    return role_list


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("roles", "write")
    role = Role(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
    )
    db.add(role)
    await db.flush()

    # Attach permissions
    for perm_str in body.permissions:
        parts = perm_str.split(":")
        if len(parts) != 2:
            continue
        resource, action = parts
        result = await db.execute(
            select(Permission).where(Permission.resource == resource, Permission.action == action)
        )
        perm = result.scalar_one_or_none()
        if perm:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.commit()
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        is_system=role.is_system, permissions=body.permissions,
    )


async def _get_role_permissions(role_id: uuid.UUID, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return [f"{row.resource}:{row.action}" for row in result.all()]
