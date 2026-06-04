"""
Approval workflow for healing actions.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.kafka_client import Topics, publish
from backend.shared.models.healing import HealingAction
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class ApprovalRequest(BaseModel):
    approver_notes: Optional[str] = None
    schedule_type: str = "immediate"    # immediate | maintenance_window


class RejectionRequest(BaseModel):
    reason: str


@router.post("/actions/{action_id}/approve", status_code=status.HTTP_200_OK)
async def approve_action(
    action_id: uuid.UUID,
    body: ApprovalRequest,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "approve")

    action = await db.get(HealingAction, action_id)
    if not action or action.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action is not pending (status={action.status})")

    action.status = "approved"
    action.approved_by = current_user.user_id
    action.approved_at = datetime.now(timezone.utc)
    await db.commit()

    # Publish to execute
    if body.schedule_type == "immediate":
        await publish(Topics.ACTIONS_APPROVED, {
            "type": "execute_approved",
            "tenant_id": str(current_user.tenant_id),
            "action_id": str(action_id),
            "action_type": action.action_type,
            "executor_type": action.executor_type,
            "parameters": action.parameters,
            "approver_notes": body.approver_notes,
        })

    return {
        "message": "Action approved",
        "action_id": str(action_id),
        "status": "approved",
        "approved_by": current_user.username,
    }


@router.post("/actions/{action_id}/reject", status_code=status.HTTP_200_OK)
async def reject_action(
    action_id: uuid.UUID,
    body: RejectionRequest,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "approve")

    action = await db.get(HealingAction, action_id)
    if not action or action.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action is not pending")

    action.status = "rejected"
    action.rejection_reason = body.reason
    action.approved_by = current_user.user_id
    action.approved_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "message": "Action rejected",
        "action_id": str(action_id),
        "rejection_reason": body.reason,
    }


@router.post("/actions/{action_id}/rollback")
async def rollback_action(
    action_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("healing", "approve")

    action = await db.get(HealingAction, action_id)
    if not action or action.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "success":
        raise HTTPException(status_code=400, detail="Can only rollback successful actions")
    if not action.rollback_plan:
        raise HTTPException(status_code=400, detail="No rollback plan available for this action")

    await publish(Topics.HEALING_TASKS, {
        "type": "rollback_action",
        "tenant_id": str(current_user.tenant_id),
        "action_id": str(action_id),
        "rollback_plan": action.rollback_plan,
        "requested_by": str(current_user.user_id),
    })

    action.status = "rollback_pending"
    await db.commit()

    return {"message": "Rollback initiated", "action_id": str(action_id)}
