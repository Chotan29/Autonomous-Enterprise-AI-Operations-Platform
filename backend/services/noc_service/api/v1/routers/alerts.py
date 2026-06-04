"""
NOC Alerts API — view and manage network alerts.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.kafka_client import Topics, publish
from backend.shared.models.alert import Alert
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class AlertResponse(BaseModel):
    id: uuid.UUID
    alert_type: str
    category: Optional[str]
    severity: str
    title: str
    description: Optional[str]
    status: str
    source_host: Optional[str]
    ai_rca: Optional[str]
    ai_suggestion: Optional[str]
    ai_confidence: Optional[float]
    is_ai_resolved: bool
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[AlertResponse])
async def list_alerts(
    current_user: AuthRequired,
    severity: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    current_user.require("alerts", "read")
    query = select(Alert).where(Alert.tenant_id == current_user.tenant_id)
    if severity:
        query = query.where(Alert.severity == severity)
    if status_filter:
        query = query.where(Alert.status == status_filter)
    if category:
        query = query.where(Alert.category == category)

    query = query.order_by(Alert.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return [AlertResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/stats")
async def alert_stats(current_user: AuthRequired, db: AsyncSession = Depends(get_db)):
    current_user.require("alerts", "read")
    result = await db.execute(
        select(Alert.severity, Alert.status, func.count())
        .where(Alert.tenant_id == current_user.tenant_id)
        .group_by(Alert.severity, Alert.status)
    )
    stats: dict = {"by_severity": {}, "by_status": {}, "total": 0}
    for severity, status_val, count in result.all():
        stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + count
        stats["by_status"][status_val] = stats["by_status"].get(status_val, 0) + count
        stats["total"] += count
    return stats


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: uuid.UUID, current_user: AuthRequired, db: AsyncSession = Depends(get_db)
):
    current_user.require("alerts", "read")
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.tenant_id == current_user.tenant_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertResponse.model_validate(alert)


@router.post("/{alert_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_alert(
    alert_id: uuid.UUID, current_user: AuthRequired, db: AsyncSession = Depends(get_db)
):
    current_user.require("alerts", "write")
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.tenant_id == current_user.tenant_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "acknowledged"
    alert.acknowledged_by = current_user.user_id
    alert.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/{alert_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_alert(
    alert_id: uuid.UUID,
    notes: Optional[str] = None,
    current_user: AuthRequired = Depends(),
    db: AsyncSession = Depends(get_db),
):
    current_user.require("alerts", "write")
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.tenant_id == current_user.tenant_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "resolved"
    alert.resolved_by = current_user.user_id
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolution_notes = notes
    await db.commit()


@router.post("/{alert_id}/trigger-rca")
async def trigger_rca(
    alert_id: uuid.UUID, current_user: AuthRequired, db: AsyncSession = Depends(get_db)
):
    """Manually trigger AI Root Cause Analysis for this alert."""
    current_user.require("alerts", "read")
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.tenant_id == current_user.tenant_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    await publish(Topics.NOC_TASKS, {
        "type": "run_noc_agent",
        "tenant_id": str(current_user.tenant_id),
        "alert_id": str(alert_id),
    })
    return {"message": "RCA analysis triggered", "alert_id": str(alert_id)}
