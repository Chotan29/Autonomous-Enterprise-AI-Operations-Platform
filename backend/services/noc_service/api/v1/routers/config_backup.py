"""
Device configuration backup and restore.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.device import Device, DeviceConfig
from backend.services.auth_service.deps import AuthRequired
from backend.services.noc_service.drivers.driver_factory import get_driver

router = APIRouter()


class ConfigResponse(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID
    config_type: str
    content_hash: str
    version: int
    is_baseline: bool
    backup_at: datetime
    storage_path: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True


@router.get("/{device_id}/configs", response_model=list[ConfigResponse])
async def list_configs(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    result = await db.execute(
        select(DeviceConfig)
        .where(DeviceConfig.device_id == device_id, DeviceConfig.tenant_id == current_user.tenant_id)
        .order_by(DeviceConfig.backup_at.desc())
        .limit(50)
    )
    return [ConfigResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/{device_id}/configs/backup")
async def backup_config(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate configuration backup for this device."""
    current_user.require("devices", "read")

    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == current_user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        driver = get_driver(device)
        config_text = await driver.get_running_config()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to retrieve config: {exc}")

    content_hash = hashlib.sha256(config_text.encode()).hexdigest()

    # Check if config changed since last backup
    last_config_result = await db.execute(
        select(DeviceConfig)
        .where(DeviceConfig.device_id == device_id)
        .order_by(DeviceConfig.backup_at.desc())
        .limit(1)
    )
    last_config = last_config_result.scalar_one_or_none()

    diff = None
    if last_config and last_config.content_hash == content_hash:
        return {
            "message": "No configuration change detected",
            "hash": content_hash,
            "changed": False,
        }

    if last_config:
        diff = _compute_diff(last_config.content, config_text)

    # Get next version
    version = (last_config.version + 1) if last_config else 1

    config_entry = DeviceConfig(
        tenant_id=current_user.tenant_id,
        device_id=device_id,
        config_type="running",
        content=config_text,
        content_hash=content_hash,
        version=version,
        backup_at=datetime.now(timezone.utc),
        backed_up_by=current_user.user_id,
        diff_from_prev=diff,
        notes=notes,
    )
    db.add(config_entry)
    await db.commit()
    await db.refresh(config_entry)

    return {
        "message": "Configuration backed up successfully",
        "config_id": str(config_entry.id),
        "hash": content_hash,
        "version": version,
        "changed": True,
        "lines_changed": diff.count("\n") if diff else 0,
    }


@router.get("/{device_id}/configs/{config_id}/content")
async def get_config_content(
    device_id: uuid.UUID,
    config_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    result = await db.execute(
        select(DeviceConfig).where(
            DeviceConfig.id == config_id,
            DeviceConfig.device_id == device_id,
            DeviceConfig.tenant_id == current_user.tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"content": config.content, "hash": config.content_hash, "version": config.version}


@router.post("/{device_id}/configs/restore")
async def restore_config(
    device_id: uuid.UUID,
    config_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    """Restore a previous configuration to the device. Requires approval in production."""
    current_user.require("devices", "write")

    device_result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == current_user.tenant_id)
    )
    device = device_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    config_result = await db.execute(
        select(DeviceConfig).where(
            DeviceConfig.id == config_id,
            DeviceConfig.tenant_id == current_user.tenant_id,
        )
    )
    config = config_result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config version not found")

    # For production: create a healing action that requires approval
    from backend.core.kafka_client import Topics, publish
    await publish(Topics.HEALING_TASKS, {
        "type": "create_action",
        "tenant_id": str(current_user.tenant_id),
        "action": {
            "action_type": "rollback_config",
            "executor_type": "ssh",
            "target_device_id": str(device_id),
            "parameters": {
                "config_content": config.content,
                "config_id": str(config_id),
                "config_version": config.version,
            },
            "ai_reasoning": f"Manual restore requested by {current_user.username}",
            "risk_level": "medium",
            "requires_approval": True,
        },
    })

    return {
        "message": "Restore action created and pending approval",
        "config_version": config.version,
        "config_hash": config.content_hash,
    }


def _compute_diff(old: str, new: str) -> str:
    import difflib
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="previous",
        tofile="current",
        n=3,
    )
    return "".join(diff)
