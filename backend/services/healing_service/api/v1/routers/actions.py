"""
Healing actions management API.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.healing import HealingAction
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class ActionResponse(BaseModel):
    id: uuid.UUID
    action_type: str
    executor_type: str
    risk_level: str
    status: str
    requires_approval: bool
    ai_reasoning: Optional[str]
    parameters: dict
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    execution_log: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/actions", response_model=list[ActionResponse])
async def list_actions(
    current_user: AuthRequired,
    status_filter: Optional[str] = Query(None, alias="status"),
    risk_level: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "read")
    query = select(HealingAction).where(HealingAction.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.where(HealingAction.status == status_filter)
    if risk_level:
        query = query.where(HealingAction.risk_level == risk_level)
    query = query.order_by(HealingAction.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return [ActionResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/actions/pending")
async def list_pending_actions(
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    """Get actions awaiting approval — for the approval dashboard."""
    current_user.require("healing", "read")
    result = await db.execute(
        select(HealingAction)
        .where(
            HealingAction.tenant_id == current_user.tenant_id,
            HealingAction.status == "pending",
            HealingAction.requires_approval == True,
        )
        .order_by(HealingAction.created_at.asc())
        .limit(50)
    )
    return [ActionResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/actions/{action_id}", response_model=ActionResponse)
async def get_action(
    action_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "read")
    action = await db.get(HealingAction, action_id)
    if not action or action.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")
    return ActionResponse.model_validate(action)


@router.get("/stats")
async def healing_stats(
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "read")
    from sqlalchemy import func
    result = await db.execute(
        select(HealingAction.status, func.count())
        .where(HealingAction.tenant_id == current_user.tenant_id)
        .group_by(HealingAction.status)
    )
    stats = {row[0]: row[1] for row in result.all()}
    total = sum(stats.values())
    success = stats.get("success", 0)
    return {
        "total": total,
        "by_status": stats,
        "success_rate_pct": round((success / total * 100) if total > 0 else 0, 1),
    }
