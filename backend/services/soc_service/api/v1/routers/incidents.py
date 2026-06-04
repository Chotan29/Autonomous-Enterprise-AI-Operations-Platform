import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.kafka_client import Topics, publish
from backend.shared.models.alert import Alert, Incident, IncidentTimeline
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "soc"
    severity: str
    priority: str = "medium"
    impact: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None
    assigned_team: Optional[str] = None
    related_alerts: list[uuid.UUID] = []
    tags: list[str] = []


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None
    assigned_team: Optional[str] = None
    priority: Optional[str] = None
    root_cause: Optional[str] = None
    resolution: Optional[str] = None


class TimelineEntry(BaseModel):
    content: str
    action_type: str = "note"
    metadata: dict = {}


class IncidentResponse(BaseModel):
    id: uuid.UUID
    incident_number: str
    title: str
    category: Optional[str]
    severity: str
    priority: str
    status: str
    impact: Optional[str]
    assigned_to: Optional[uuid.UUID]
    assigned_team: Optional[str]
    root_cause: Optional[str]
    resolution: Optional[str]
    ai_summary: Optional[str]
    mitre_tactics: list
    mitre_techniques: list
    tags: list
    related_alerts: list
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    current_user: AuthRequired,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to_me: bool = False,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "read")
    query = select(Incident).where(Incident.tenant_id == current_user.tenant_id)

    if status_filter:
        query = query.where(Incident.status == status_filter)
    if severity:
        query = query.where(Incident.severity == severity)
    if category:
        query = query.where(Incident.category == category)
    if assigned_to_me:
        query = query.where(Incident.assigned_to == current_user.user_id)

    query = query.order_by(Incident.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return [IncidentResponse.model_validate(i) for i in result.scalars().all()]


@router.post("/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "write")

    # Generate incident number
    count_result = await db.execute(
        select(func.count()).select_from(Incident).where(Incident.tenant_id == current_user.tenant_id)
    )
    count = count_result.scalar_one() + 1
    incident_number = f"INC-{datetime.now(timezone.utc).strftime('%Y')}-{count:06d}"

    incident = Incident(
        tenant_id=current_user.tenant_id,
        incident_number=incident_number,
        title=body.title,
        description=body.description,
        category=body.category,
        severity=body.severity,
        priority=body.priority,
        impact=body.impact,
        assigned_to=body.assigned_to,
        assigned_team=body.assigned_team,
        tags=body.tags,
        related_alerts=[str(a) for a in body.related_alerts],
    )
    db.add(incident)
    await db.flush()

    # Initial timeline entry
    db.add(IncidentTimeline(
        incident_id=incident.id,
        user_id=current_user.user_id,
        action_type="created",
        content=f"Incident created by {current_user.username}",
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    await db.refresh(incident)

    # Trigger AI analysis
    await publish(Topics.SOC_TASKS, {
        "type": "analyze_incident",
        "tenant_id": str(current_user.tenant_id),
        "incident_id": str(incident.id),
        "incident_data": body.model_dump(mode="json"),
    })

    return IncidentResponse.model_validate(incident)


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "read")
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.tenant_id == current_user.tenant_id
        )
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentResponse.model_validate(incident)


@router.put("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "write")
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.tenant_id == current_user.tenant_id
        )
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    old_status = incident.status
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(incident, field, value)

    if body.status and body.status != old_status:
        if body.status == "resolved":
            incident.resolved_at = datetime.now(timezone.utc)
        db.add(IncidentTimeline(
            incident_id=incident.id,
            user_id=current_user.user_id,
            action_type="status_change",
            content=f"Status changed from {old_status} to {body.status} by {current_user.username}",
            created_at=datetime.now(timezone.utc),
        ))

    await db.commit()
    await db.refresh(incident)
    return IncidentResponse.model_validate(incident)


@router.post("/incidents/{incident_id}/timeline")
async def add_timeline_entry(
    incident_id: uuid.UUID,
    body: TimelineEntry,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "write")
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.tenant_id == current_user.tenant_id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Incident not found")

    entry = IncidentTimeline(
        incident_id=incident_id,
        user_id=current_user.user_id,
        action_type=body.action_type,
        content=body.content,
        metadata=body.metadata,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()
    return {"message": "Timeline entry added", "entry_id": str(entry.id)}


@router.get("/incidents/{incident_id}/timeline")
async def get_timeline(
    incident_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "read")
    result = await db.execute(
        select(IncidentTimeline)
        .where(IncidentTimeline.incident_id == incident_id)
        .order_by(IncidentTimeline.created_at.asc())
    )
    return [
        {
            "id": str(e.id),
            "action_type": e.action_type,
            "content": e.content,
            "user_id": str(e.user_id) if e.user_id else None,
            "metadata": e.metadata,
            "created_at": e.created_at,
        }
        for e in result.scalars().all()
    ]


@router.get("/incidents/{incident_id}/ai-summary")
async def get_ai_summary(
    incident_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("incidents", "read")
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.tenant_id == current_user.tenant_id
        )
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.ai_summary:
        return {"summary": incident.ai_summary, "cached": True}

    # Generate on demand
    import httpx
    from backend.core.config import settings
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"http://localhost:{settings.AI_SERVICE_PORT}/api/v1/ai/analyze/incident",
            json={"incident_data": IncidentResponse.model_validate(incident).model_dump(mode="json")},
            headers={"Authorization": "internal"},
        )
    return {"summary": resp.json().get("raw_response", ""), "cached": False}
