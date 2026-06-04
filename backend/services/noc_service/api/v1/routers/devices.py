import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, IPvAnyAddress
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.kafka_client import Topics, publish
from backend.shared.models.device import Device, DeviceInterface, DeviceNeighbor
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class DeviceCreate(BaseModel):
    hostname: str
    ip_address: str
    vendor: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    snmp_version: str = "v2c"
    snmp_community: Optional[str] = None
    snmp_config: Optional[dict] = None
    ssh_config: Optional[dict] = None
    api_config: Optional[dict] = None
    location: Optional[str] = None
    site_code: Optional[str] = None
    tags: list[str] = []


class DeviceUpdate(BaseModel):
    display_name: Optional[str] = None
    location: Optional[str] = None
    site_code: Optional[str] = None
    tags: Optional[list[str]] = None
    is_managed: Optional[bool] = None
    snmp_version: Optional[str] = None
    snmp_community: Optional[str] = None


class DeviceResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    hostname: str
    display_name: Optional[str]
    ip_address: str
    vendor: Optional[str]
    model: Optional[str]
    category: Optional[str]
    status: str
    location: Optional[str]
    site_code: Optional[str]
    os_version: Optional[str]
    firmware_version: Optional[str]
    uptime_seconds: Optional[int]
    last_seen: Optional[datetime]
    last_poll: Optional[datetime]
    ai_health_score: Optional[int]
    last_cpu_util: Optional[float]
    last_mem_util: Optional[float]
    tags: list
    is_managed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    page: int
    per_page: int


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=DeviceListResponse)
async def list_devices(
    current_user: AuthRequired,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    status: Optional[str] = None,
    vendor: Optional[str] = None,
    site_code: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    query = select(Device).where(Device.tenant_id == current_user.tenant_id)

    if status:
        query = query.where(Device.status == status)
    if vendor:
        query = query.where(Device.vendor.ilike(f"%{vendor}%"))
    if site_code:
        query = query.where(Device.site_code == site_code)
    if search:
        query = query.where(
            or_(
                Device.hostname.ilike(f"%{search}%"),
                Device.ip_address.ilike(f"%{search}%"),
                Device.display_name.ilike(f"%{search}%"),
            )
        )

    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page).order_by(Device.hostname)
    result = await db.execute(query)
    devices = result.scalars().all()

    return DeviceListResponse(
        items=[DeviceResponse.model_validate(d) for d in devices],
        total=total, page=page, per_page=per_page,
    )


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "write")

    existing = await db.execute(
        select(Device).where(
            Device.tenant_id == current_user.tenant_id,
            Device.ip_address == body.ip_address,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Device with IP {body.ip_address} already exists")

    device = Device(
        tenant_id=current_user.tenant_id,
        hostname=body.hostname,
        ip_address=body.ip_address,
        vendor=body.vendor,
        model=body.model,
        category=body.category,
        snmp_version=body.snmp_version,
        snmp_community=body.snmp_community,
        snmp_config=body.snmp_config,
        ssh_config=body.ssh_config,
        api_config=body.api_config,
        location=body.location,
        site_code=body.site_code,
        tags=body.tags,
        status="unknown",
        discovery_method="manual",
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    # Trigger initial poll
    await publish(Topics.NOC_TASKS, {
        "type": "poll_device",
        "device_id": str(device.id),
        "tenant_id": str(current_user.tenant_id),
        "priority": "high",
    })

    return DeviceResponse.model_validate(device)


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    return DeviceResponse.model_validate(device)


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "write")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(device, field, value)
    await db.commit()
    await db.refresh(device)
    return DeviceResponse.model_validate(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "delete")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    await db.delete(device)
    await db.commit()


@router.post("/{device_id}/poll")
async def force_poll(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    await publish(Topics.NOC_TASKS, {
        "type": "poll_device",
        "device_id": str(device.id),
        "tenant_id": str(current_user.tenant_id),
        "priority": "high",
    })
    return {"message": f"Poll triggered for {device.hostname}", "device_id": str(device.id)}


@router.post("/{device_id}/ping")
async def ping_device(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "3", "-W", "2", device.ip_address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        reachable = proc.returncode == 0
        return {
            "device_id": str(device.id),
            "hostname": device.hostname,
            "ip_address": device.ip_address,
            "reachable": reachable,
            "output": stdout.decode()[:500],
        }
    except asyncio.TimeoutError:
        return {"device_id": str(device.id), "hostname": device.hostname, "reachable": False, "output": "Timeout"}


@router.get("/{device_id}/interfaces")
async def get_interfaces(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    result = await db.execute(
        select(DeviceInterface).where(DeviceInterface.device_id == device_id)
        .order_by(DeviceInterface.if_index)
    )
    interfaces = result.scalars().all()
    return [
        {
            "if_index": i.if_index, "if_name": i.if_name, "if_alias": i.if_alias,
            "if_type": i.if_type, "admin_status": i.admin_status, "oper_status": i.oper_status,
            "speed_bps": i.speed_bps, "in_octets": i.in_octets, "out_octets": i.out_octets,
            "in_errors": i.in_errors, "out_errors": i.out_errors,
            "ip_addresses": i.ip_addresses, "last_updated": i.last_updated,
        }
        for i in interfaces
    ]


@router.get("/{device_id}/neighbors")
async def get_neighbors(
    device_id: uuid.UUID,
    current_user: AuthRequired,
    db: AsyncSession = Depends(get_db),
):
    current_user.require("devices", "read")
    device = await _get_device_or_404(device_id, current_user.tenant_id, db)
    result = await db.execute(
        select(DeviceNeighbor).where(DeviceNeighbor.local_device_id == device_id)
    )
    return [
        {
            "local_port": n.local_port,
            "remote_hostname": n.remote_hostname,
            "remote_ip": n.remote_ip,
            "remote_port": n.remote_port,
            "protocol": n.protocol,
            "last_seen": n.last_seen,
        }
        for n in result.scalars().all()
    ]


async def _get_device_or_404(
    device_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
) -> Device:
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == tenant_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device
