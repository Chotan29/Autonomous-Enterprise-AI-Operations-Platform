"""
SIEM query and log search API.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch

from backend.core.config import settings
from backend.services.auth_service.deps import AuthRequired

router = APIRouter()


def _get_es() -> AsyncElasticsearch:
    kwargs = {"hosts": [settings.ELASTICSEARCH_URL]}
    if settings.ELASTICSEARCH_USERNAME:
        kwargs["http_auth"] = (settings.ELASTICSEARCH_USERNAME, settings.ELASTICSEARCH_PASSWORD)
    return AsyncElasticsearch(**kwargs)


class EventSearchRequest(BaseModel):
    query: str
    time_range: str = "24h"
    limit: int = 100
    filters: dict = {}


@router.post("/events/search")
async def search_events(body: EventSearchRequest, current_user: AuthRequired):
    current_user.require("alerts", "read")
    es = _get_es()
    try:
        time_map = {"1h": "now-1h", "24h": "now-24h", "7d": "now-7d", "30d": "now-30d"}
        from_time = time_map.get(body.time_range, "now-24h")

        query = {
            "bool": {
                "must": [
                    {"term": {"tenant_id": str(current_user.tenant_id)}},
                    {"range": {"@timestamp": {"gte": from_time}}},
                    {"query_string": {"query": body.query}} if body.query else {"match_all": {}},
                ]
            }
        }

        resp = await es.search(
            index=f"{settings.ELASTICSEARCH_INDEX_PREFIX}-siem-*",
            body={"query": query, "size": body.limit, "sort": [{"@timestamp": "desc"}]},
        )
        return {
            "total": resp["hits"]["total"]["value"],
            "events": [hit["_source"] for hit in resp["hits"]["hits"]],
        }
    finally:
        await es.close()


@router.get("/events/stats")
async def event_stats(
    current_user: AuthRequired,
    time_range: str = Query("24h"),
):
    """Get event statistics by severity and category."""
    current_user.require("alerts", "read")
    es = _get_es()
    try:
        time_map = {"1h": "now-1h", "24h": "now-24h", "7d": "now-7d"}
        from_time = time_map.get(time_range, "now-24h")

        resp = await es.search(
            index=f"{settings.ELASTICSEARCH_INDEX_PREFIX}-siem-*",
            body={
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"tenant_id": str(current_user.tenant_id)}},
                            {"range": {"@timestamp": {"gte": from_time}}},
                        ]
                    }
                },
                "aggs": {
                    "by_severity": {"terms": {"field": "severity"}},
                    "by_category": {"terms": {"field": "event_category"}},
                    "over_time": {
                        "date_histogram": {
                            "field": "@timestamp",
                            "calendar_interval": "1h" if time_range in ("1h", "24h") else "1d",
                        }
                    },
                },
                "size": 0,
            },
        )
        aggs = resp.get("aggregations", {})
        return {
            "total": resp["hits"]["total"]["value"],
            "by_severity": {b["key"]: b["doc_count"] for b in aggs.get("by_severity", {}).get("buckets", [])},
            "by_category": {b["key"]: b["doc_count"] for b in aggs.get("by_category", {}).get("buckets", [])},
            "timeline": [
                {"time": b["key_as_string"], "count": b["doc_count"]}
                for b in aggs.get("over_time", {}).get("buckets", [])
            ],
        }
    finally:
        await es.close()
