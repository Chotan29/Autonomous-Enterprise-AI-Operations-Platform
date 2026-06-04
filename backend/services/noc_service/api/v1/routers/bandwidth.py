"""
Bandwidth analytics API.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


@router.get("/top")
async def get_top_talkers(
    current_user: AuthRequired,
    limit: int = Query(10, ge=1, le=50),
    time_range: str = Query("1h"),
):
    current_user.require("devices", "read")
    return {"top_talkers": [], "time_range": time_range}


@router.get("/trends")
async def get_bandwidth_trends(
    current_user: AuthRequired,
    device_id: Optional[uuid.UUID] = None,
    interface: Optional[str] = None,
    time_range: str = Query("24h"),
):
    current_user.require("devices", "read")
    return {"trends": [], "device_id": str(device_id) if device_id else None}


@router.get("/forecast")
async def get_bandwidth_forecast(
    current_user: AuthRequired,
    device_id: Optional[uuid.UUID] = None,
    horizon_hours: int = Query(24, ge=1, le=168),
):
    current_user.require("devices", "read")
    return {"forecasts": [], "horizon_hours": horizon_hours, "model": "prophet"}
