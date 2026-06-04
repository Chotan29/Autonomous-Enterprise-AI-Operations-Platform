"""
Network discovery API — IP scanning, SNMP discovery, topology rebuild.
"""
import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.kafka_client import Topics, publish
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


class ScanRequest(BaseModel):
    ip_range: str          # e.g. "192.168.1.0/24" or "10.0.0.1-10.0.0.50"
    snmp_community: str = "public"
    snmp_version: str = "v2c"
    ports: list[int] = [22, 23, 80, 443, 161, 830]
    timeout_seconds: int = 30


class SNMPDiscoveryRequest(BaseModel):
    ip_range: str
    snmp_community: str = "public"
    snmp_version: str = "v2c"


@router.post("/scan")
async def scan_network(body: ScanRequest, current_user: AuthRequired):
    """Trigger an IP range scan to discover new devices."""
    current_user.require("devices", "write")
    job_id = str(uuid.uuid4())
    await publish(Topics.NOC_TASKS, {
        "type": "scan_network",
        "tenant_id": str(current_user.tenant_id),
        "job_id": job_id,
        "ip_range": body.ip_range,
        "snmp_community": body.snmp_community,
        "snmp_version": body.snmp_version,
        "ports": body.ports,
        "timeout": body.timeout_seconds,
    })
    return {
        "message": "Network scan started",
        "job_id": job_id,
        "ip_range": body.ip_range,
        "status": "running",
    }


@router.post("/snmp")
async def snmp_discovery(body: SNMPDiscoveryRequest, current_user: AuthRequired):
    """Discover devices via SNMP walk."""
    current_user.require("devices", "write")
    job_id = str(uuid.uuid4())
    await publish(Topics.NOC_TASKS, {
        "type": "snmp_discovery",
        "tenant_id": str(current_user.tenant_id),
        "job_id": job_id,
        "ip_range": body.ip_range,
        "community": body.snmp_community,
        "version": body.snmp_version,
    })
    return {"message": "SNMP discovery started", "job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_discovery_job(job_id: str, current_user: AuthRequired):
    """Get status of a discovery job."""
    current_user.require("devices", "read")
    # In production: query Redis or DB for job status
    return {"job_id": job_id, "status": "running", "devices_found": 0}
