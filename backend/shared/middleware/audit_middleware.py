import json
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.kafka_client import Topics, publish


SKIP_AUDIT_PATHS = {"/health", "/health/ready", "/health/live", "/metrics", "/docs", "/openapi.json"}

SENSITIVE_ACTIONS = {
    "POST:/api/v1/healing/actions",
    "POST:/api/v1/noc/devices",
    "DELETE:/api/v1/noc/devices",
    "POST:/api/v1/noc/devices/configs/restore",
    "POST:/api/v1/auth/users",
    "DELETE:/api/v1/auth/users",
    "POST:/api/v1/auth/roles",
}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in SKIP_AUDIT_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start_time = time.time()

        response = await call_next(request)

        duration_ms = int((time.time() - start_time) * 1000)
        user_id = getattr(request.state, "user_id", None)
        tenant_id = getattr(request.state, "tenant_id", None)

        if user_id:
            action_key = f"{request.method}:{request.url.path}"
            audit_entry = {
                "id": request_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action_key,
                "resource_type": _extract_resource_type(request.url.path),
                "resource_id": _extract_resource_id(request.url.path),
                "ip_address": _get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "status": "success" if response.status_code < 400 else "failure",
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            }
            try:
                await publish(Topics.DEVICE_EVENTS, {
                    "type": "audit_log",
                    "data": audit_entry
                })
            except Exception:
                pass

        response.headers["X-Request-ID"] = request_id
        return response


def _extract_resource_type(path: str) -> str:
    parts = [p for p in path.split("/") if p and p not in ("api", "v1")]
    return parts[0] if parts else "unknown"


def _extract_resource_id(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    for i, part in enumerate(parts):
        # UUIDs are 36 chars
        if len(part) == 36 and part.count("-") == 4:
            return part
    return None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
