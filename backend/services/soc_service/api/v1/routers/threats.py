"""
Threat intelligence management API.
"""
import uuid
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.alert import Alert
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class IOCCreate(BaseModel):
    ioc_type: str     # ip | domain | hash | url | email
    ioc_value: str
    threat_type: Optional[str] = None
    confidence: int = 70
    severity: str = "medium"
    source: str = "manual"
    tags: list[str] = []


class IOCResponse(BaseModel):
    ioc_type: str
    ioc_value: str
    threat_type: Optional[str]
    confidence: int
    severity: str
    source: str
    tags: list


@router.get("/threat-intel/iocs")
async def list_iocs(
    current_user: AuthRequired,
    ioc_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    current_user.require("alerts", "read")
    # In production this queries a ThreatIntel table
    # For now return placeholder
    return {"iocs": [], "total": 0}


@router.post("/threat-intel/iocs/lookup")
async def lookup_ioc(
    ioc_value: str,
    current_user: AuthRequired,
):
    """Check if a value matches any known IOC."""
    current_user.require("alerts", "read")
    # Query local threat intel DB
    return {"matched": False, "ioc_value": ioc_value, "matches": []}


@router.get("/threat-intel/mitre")
async def get_mitre_coverage(current_user: AuthRequired):
    """Return detected MITRE ATT&CK tactics/techniques coverage."""
    current_user.require("alerts", "read")
    from sqlalchemy import select, func
    from backend.core.database import get_db_context
    from backend.shared.models.alert import Incident

    async with get_db_context() as db:
        result = await db.execute(
            select(Incident.mitre_tactics, Incident.mitre_techniques)
            .where(Incident.tenant_id == current_user.tenant_id)
            .limit(1000)
        )
        rows = result.all()

    tactic_counts: dict = {}
    technique_counts: dict = {}
    for row in rows:
        for tactic in (row.mitre_tactics or []):
            tactic_counts[tactic] = tactic_counts.get(tactic, 0) + 1
        for technique in (row.mitre_techniques or []):
            technique_counts[technique] = technique_counts.get(technique, 0) + 1

    return {
        "tactics": tactic_counts,
        "techniques": technique_counts,
        "total_incidents_analyzed": len(rows),
    }
