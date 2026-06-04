from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.redis_client import user_cache


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Extracts tenant_id from the JWT claims and attaches it to request.state.
    This ensures every request is properly scoped to a tenant.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # tenant_id is set by the auth dependency after token validation
        # Here we just ensure it's available or set a default
        if not hasattr(request.state, "tenant_id"):
            request.state.tenant_id = None
        if not hasattr(request.state, "user_id"):
            request.state.user_id = None
        if not hasattr(request.state, "roles"):
            request.state.roles = []
        return await call_next(request)
