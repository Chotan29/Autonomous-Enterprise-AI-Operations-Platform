"""
User Entity Behavior Analytics (UEBA) API.
"""
from typing import Optional
from fastapi import APIRouter, Query
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


@router.get("/entities")
async def list_entities(
    current_user: AuthRequired,
    entity_type: Optional[str] = None,
    min_risk_score: int = Query(0, ge=0, le=100),
    limit: int = Query(50, le=200),
):
    current_user.require("alerts", "read")
    return {"entities": [], "total": 0}


@router.get("/anomalies")
async def get_anomalies(
    current_user: AuthRequired,
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    current_user.require("alerts", "read")
    return {"anomalies": [], "total": 0}


@router.get("/risk-scores")
async def get_risk_scores(
    current_user: AuthRequired,
    top_n: int = Query(10, ge=1, le=50),
):
    """Get entities with highest risk scores."""
    current_user.require("alerts", "read")
    return {"high_risk_entities": [], "total_monitored": 0}
