"""
Network topology API — builds and returns graph data for D3.js visualization.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.shared.models.device import Device, DeviceNeighbor
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


@router.get("/")
async def get_topology(
    current_user: AuthRequired,
    site_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return full topology as nodes + edges for D3.js rendering."""
    current_user.require("devices", "read")

    query = select(Device).where(Device.tenant_id == current_user.tenant_id)
    if site_code:
        query = query.where(Device.site_code == site_code)

    result = await db.execute(query)
    devices = result.scalars().all()
    device_map = {str(d.id): d for d in devices}

    # Build nodes
    nodes = [
        {
            "id": str(d.id),
            "hostname": d.hostname,
            "display_name": d.display_name or d.hostname,
            "ip": d.ip_address,
            "vendor": d.vendor,
            "category": d.category,
            "status": d.status,
            "location": d.location,
            "site_code": d.site_code,
            "cpu": d.last_cpu_util,
            "mem": d.last_mem_util,
            "health_score": d.ai_health_score,
        }
        for d in devices
    ]

    # Build edges from neighbors
    edge_result = await db.execute(
        select(DeviceNeighbor).where(DeviceNeighbor.tenant_id == current_user.tenant_id)
    )
    neighbors = edge_result.scalars().all()

    edges = []
    seen_edges: set[tuple] = set()

    for n in neighbors:
        src = str(n.local_device_id)
        dst = str(n.remote_device_id) if n.remote_device_id else None

        if dst and dst in device_map:
            edge_key = tuple(sorted([src, dst]))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                src_dev = device_map.get(src)
                dst_dev = device_map.get(dst)
                edges.append({
                    "id": f"{src}-{dst}",
                    "source": src,
                    "target": dst,
                    "source_port": n.local_port,
                    "target_port": n.remote_port,
                    "protocol": n.protocol,
                    "status": "up" if (src_dev and dst_dev and
                                       src_dev.status == "online" and
                                       dst_dev.status == "online") else "degraded",
                })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_devices": len(nodes),
            "online": sum(1 for n in nodes if n["status"] == "online"),
            "offline": sum(1 for n in nodes if n["status"] == "offline"),
            "degraded": sum(1 for n in nodes if n["status"] == "degraded"),
            "total_links": len(edges),
        },
    }


@router.get("/devices/{device_id}")
async def get_device_neighborhood(
    device_id: uuid.UUID,
    hops: int = 2,
    current_user: AuthRequired = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Get N-hop neighborhood graph for a specific device."""
    current_user.require("devices", "read")

    visited: set[str] = set()
    frontier = {str(device_id)}
    all_device_ids: set[str] = set()

    for _ in range(hops):
        if not frontier:
            break
        neighbor_result = await db.execute(
            select(DeviceNeighbor).where(
                DeviceNeighbor.local_device_id.in_([uuid.UUID(fid) for fid in frontier]),
                DeviceNeighbor.tenant_id == current_user.tenant_id,
            )
        )
        new_frontier: set[str] = set()
        for n in neighbor_result.scalars().all():
            if n.remote_device_id:
                rid = str(n.remote_device_id)
                if rid not in visited:
                    new_frontier.add(rid)
                    all_device_ids.add(rid)
        visited.update(frontier)
        all_device_ids.update(frontier)
        frontier = new_frontier - visited

    if not all_device_ids:
        raise HTTPException(status_code=404, detail="Device not found or no neighbors")

    dev_result = await db.execute(
        select(Device).where(
            Device.id.in_([uuid.UUID(did) for did in all_device_ids]),
            Device.tenant_id == current_user.tenant_id,
        )
    )
    devices = dev_result.scalars().all()
    device_map = {str(d.id): d for d in devices}

    nodes = [
        {
            "id": str(d.id), "hostname": d.hostname,
            "ip": d.ip_address, "vendor": d.vendor,
            "status": d.status, "is_focus": str(d.id) == str(device_id),
        }
        for d in devices
    ]

    edge_result = await db.execute(
        select(DeviceNeighbor).where(
            DeviceNeighbor.local_device_id.in_([uuid.UUID(did) for did in all_device_ids]),
            DeviceNeighbor.tenant_id == current_user.tenant_id,
        )
    )
    edges = [
        {
            "source": str(n.local_device_id),
            "target": str(n.remote_device_id),
            "source_port": n.local_port,
            "target_port": n.remote_port,
            "protocol": n.protocol,
        }
        for n in edge_result.scalars().all()
        if n.remote_device_id and str(n.remote_device_id) in device_map
    ]

    return {"nodes": nodes, "edges": edges, "focus_device_id": str(device_id)}
