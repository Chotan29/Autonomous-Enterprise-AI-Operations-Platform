"""
FastAPI application for the Network Discovery Tool.

Provides:
  * Session login (Bootstrap login page + cookie session).
  * A Bootstrap web dashboard (live count, devices table, search, vendor
    filter, refresh-scan button, scan history, per-device history).
  * REST API endpoints:  POST /api/scan, GET /api/devices, GET /api/history
    (+ /api/stats, /api/vendors, /api/export, /api/device/{key}/history).

The app can be **mounted** into the existing noc_service FastAPI instance via
``create_app()`` / ``get_router()``, or run **standalone** via ``run.py``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from backend.services.noc_service.discovery import exporters
from backend.services.noc_service.discovery.auth import (
    current_user,
    login_user,
    logout_user,
    require_user,
)
from backend.services.noc_service.discovery.config import discovery_settings
from backend.services.noc_service.discovery.scanner import NetworkScanner
from backend.services.noc_service.discovery.store import DiscoveryStore

logger = logging.getLogger("discovery.app")

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Render a Jinja2 template to an HTMLResponse.

    Done manually (rather than via ``TemplateResponse``) so the tool is
    insensitive to differences in the installed Starlette's argument ordering.
    """
    ctx = {"request": request, **(context or {})}
    html = templates.get_template(name).render(**ctx)
    return HTMLResponse(content=html, status_code=status_code)


# Shared singletons
store = DiscoveryStore(discovery_settings.db_path)
scanner = NetworkScanner(discovery_settings)
_scan_lock = asyncio.Lock()


# ── Schemas ──────────────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    subnet: Optional[str] = None  # None => auto-detect local subnet


# ── Router (mountable) ───────────────────────────────────────────────────────
def get_router() -> APIRouter:
    router = APIRouter()

    # ---- pages ----
    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not current_user(request):
            return RedirectResponse(url="login", status_code=302)
        return render(request, "dashboard.html",
                      {"user": current_user(request), "version": "1.0.0"})

    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str | None = None):
        if current_user(request):
            return RedirectResponse(url=".", status_code=302)
        return render(request, "login.html", {"error": error})

    @router.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        ok = await asyncio.to_thread(store.verify_login, username, password)
        if not ok:
            return render(request, "login.html",
                          {"error": "Invalid username or password."}, status_code=401)
        login_user(request, username)
        return RedirectResponse(url=".", status_code=302)

    @router.get("/logout")
    async def logout(request: Request):
        logout_user(request)
        return RedirectResponse(url="login", status_code=302)

    # ---- REST API ----
    @router.post("/api/scan")
    async def api_scan(body: ScanRequest, user: str = Depends(require_user)):
        if _scan_lock.locked():
            raise HTTPException(status_code=409, detail="A scan is already running.")
        async with _scan_lock:
            try:
                target = scanner.resolve_subnet(body.subnet)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            scan_id = await asyncio.to_thread(store.start_scan, target, "manual", user)
            result = await asyncio.to_thread(scanner.scan, target)
            await asyncio.to_thread(
                store.finish_scan, scan_id,
                [h.to_dict() for h in result.hosts], result.duration,
            )
            return {
                "scan_id": scan_id,
                "subnet": result.subnet,
                "method": result.method,
                "duration_sec": round(result.duration, 2),
                "hosts_found": len(result.hosts),
                "devices": [h.to_dict() for h in result.hosts],
            }

    @router.get("/api/devices")
    async def api_devices(
        user: str = Depends(require_user),
        status: Optional[str] = Query("online"),
        vendor: Optional[str] = None,
        device_type: Optional[str] = None,
        search: Optional[str] = None,
    ):
        status_filter = None if status in (None, "all", "") else status
        devices = await asyncio.to_thread(
            store.list_devices, status=status_filter, vendor=vendor,
            device_type=device_type, search=search,
        )
        return {"count": len(devices), "devices": devices}

    @router.get("/api/history")
    async def api_history(user: str = Depends(require_user), limit: int = 50):
        return {"scans": await asyncio.to_thread(store.scan_history, limit)}

    @router.get("/api/device/{device_key}/history")
    async def api_device_history(device_key: str, user: str = Depends(require_user)):
        return {"history": await asyncio.to_thread(store.device_history, device_key)}

    @router.get("/api/stats")
    async def api_stats(user: str = Depends(require_user)):
        return await asyncio.to_thread(store.stats)

    @router.get("/api/vendors")
    async def api_vendors(user: str = Depends(require_user)):
        return {"vendors": await asyncio.to_thread(store.vendors)}

    @router.get("/api/export")
    async def api_export(
        fmt: str = Query("csv", pattern="^(csv|json|excel)$"),
        status: Optional[str] = Query("online"),
        user: str = Depends(require_user),
    ):
        status_filter = None if status in (None, "all", "") else status
        devices = await asyncio.to_thread(store.list_devices, status=status_filter)
        out_dir = discovery_settings.export_dir
        if fmt == "csv":
            path = await asyncio.to_thread(exporters.export_csv, devices, out_dir)
            media = "text/csv"
        elif fmt == "json":
            path = await asyncio.to_thread(exporters.export_json, devices, out_dir)
            media = "application/json"
        else:
            path = await asyncio.to_thread(exporters.export_excel, devices, out_dir)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(str(path), media_type=media, filename=Path(path).name)

    return router


# ── Standalone app factory ───────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="Network Discovery Tool",
        description="Local network inventory & discovery (nmap + scapy + dashboard).",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=discovery_settings.SECRET_KEY,
        session_cookie=discovery_settings.SESSION_COOKIE,
        max_age=discovery_settings.SESSION_MAX_AGE,
        same_site="lax",
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(_BASE / "static")),
        name="discovery-static",
    )

    @app.on_event("startup")
    async def _startup():
        store.ensure_admin(
            discovery_settings.ADMIN_USERNAME, discovery_settings.ADMIN_PASSWORD
        )
        logger.info("Discovery store ready at %s", discovery_settings.db_path)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "network-discovery"}

    app.include_router(get_router())
    return app


app = create_app()
