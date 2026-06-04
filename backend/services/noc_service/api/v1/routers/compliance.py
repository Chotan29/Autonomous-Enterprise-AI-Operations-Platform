"""
Device compliance checking API.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.device import Device, DeviceConfig
from backend.services.auth_service.deps import AuthRequired
from backend.services.ai_service.prompts.noc_prompts import NOC_COMPLIANCE_SYSTEM
from backend.services.ai_service.llm.model_router import llm

router = APIRouter()
import re
import json


@router.get("/summary")
async def compliance_summary(
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("compliance", "read")
    from sqlalchemy import select, func
    result = await db.execute(
        select(func.count()).select_from(Device)
        .where(Device.tenant_id == current_user.tenant_id, Device.is_managed == True)
    )
    total = result.scalar_one()
    return {
        "total_devices": total,
        "compliant": 0,
        "non_compliant": 0,
        "not_checked": total,
        "compliance_rate_pct": 0.0,
    }


@router.post("/devices/{device_id}/check")
async def check_device_compliance(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    """Run AI-powered compliance check against latest config backup."""
    current_user.require("compliance", "read")

    from sqlalchemy import select
    device_result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == current_user.tenant_id)
    )
    device = device_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Get latest config
    config_result = await db.execute(
        select(DeviceConfig)
        .where(DeviceConfig.device_id == device_id)
        .order_by(DeviceConfig.backup_at.desc())
        .limit(1)
    )
    config = config_result.scalar_one_or_none()
    if not config:
        return {"error": "No configuration backup found. Run a backup first."}

    prompt = f"""Perform a compliance check on this {device.vendor} {device.category} configuration.
Check against CIS and internal security standards.

DEVICE: {device.hostname} ({device.vendor} {device.model})
CONFIGURATION:
{config.content[:8000]}

Check for: SSH v2, no telnet, AAA enabled, logging configured, NTP configured,
no default credentials visible, SNMP v3 or community string restrictions."""

    response = await llm.generate(
        prompt=prompt,
        system_prompt=NOC_COMPLIANCE_SYSTEM,
        temperature=0.05,
    )

    try:
        json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
        compliance_result = json.loads(json_match.group()) if json_match else {}
    except Exception:
        compliance_result = {"overall_status": "error", "raw": response.content}

    return {
        "device_id": str(device_id),
        "hostname": device.hostname,
        "config_version": config.version,
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "result": compliance_result,
    }
