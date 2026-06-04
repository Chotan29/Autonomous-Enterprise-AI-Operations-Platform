import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.tenant import Tenant
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class TenantCreate(BaseModel):
    code: str
    name: str
    tier: str = "enterprise"
    compliance_mode: Optional[str] = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    tier: str
    compliance_mode: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=list[TenantResponse])
async def list_tenants(current_user: AuthRequired, db: AsyncSession = Depends(get_db)):
    if "super_admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="Super admin required")
    result = await db.execute(select(Tenant))
    return [TenantResponse.model_validate(t) for t in result.scalars().all()]


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    if "super_admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="Super admin required")

    existing = await db.execute(select(Tenant).where(Tenant.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Tenant code '{body.code}' already exists")

    tenant = Tenant(
        code=body.code,
        name=body.name,
        schema_name=f"tenant_{body.code.lower().replace('-', '_')}",
        tier=body.tier,
        compliance_mode=body.compliance_mode,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return TenantResponse.model_validate(tenant)
