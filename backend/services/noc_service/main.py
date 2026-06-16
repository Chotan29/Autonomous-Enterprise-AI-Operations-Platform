import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from backend.core.config import settings
from backend.core.database import create_all_tables
from backend.core.kafka_client import consume_forever, Topics
from backend.shared.middleware.audit_middleware import AuditMiddleware
from backend.shared.middleware.tenant_middleware import TenantMiddleware

from backend.services.noc_service.api.v1.routers import (
    devices, topology, alerts, bandwidth, config_backup, compliance, discovery,
)
from backend.services.noc_service.tasks.snmp_poller import SNMPPoller


_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    # Start background SNMP poller
    poller = SNMPPoller()
    _background_tasks.append(asyncio.create_task(poller.run_forever()))
    yield
    for task in _background_tasks:
        task.cancel()


app = FastAPI(
    title="AEAOP NOC Service",
    description="AI-Powered Network Operations Center",
    version=settings.APP_VERSION,
    debug=settings.APP_DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)
app.add_middleware(AuditMiddleware)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Routers
app.include_router(devices.router,       prefix="/api/v1/noc/devices",    tags=["Devices"])
app.include_router(topology.router,      prefix="/api/v1/noc/topology",   tags=["Topology"])
app.include_router(alerts.router,        prefix="/api/v1/noc/alerts",     tags=["NOC Alerts"])
app.include_router(bandwidth.router,     prefix="/api/v1/noc/bandwidth",  tags=["Bandwidth"])
app.include_router(config_backup.router, prefix="/api/v1/noc/devices",    tags=["Config Backup"])
app.include_router(compliance.router,    prefix="/api/v1/noc/compliance", tags=["Compliance"])
app.include_router(discovery.router,     prefix="/api/v1/noc/discovery",  tags=["Discovery"])

# ── Network Discovery Tool (self-contained dashboard + REST API + session auth)
# Mounted as a sub-application so it keeps its own SessionMiddleware and SQLite
# store, independent of the platform's JWT/Postgres stack. Available at
# /discovery/ (dashboard) and /discovery/api/{scan,devices,history}.
try:
    from backend.services.noc_service.discovery.app import create_app as _create_discovery_app
    app.mount("/discovery", _create_discovery_app(), name="network-discovery")
except Exception as _exc:  # pragma: no cover - optional component
    import logging
    logging.getLogger("noc.main").warning("Network Discovery tool not mounted: %s", _exc)


@app.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "noc"}


@app.get("/health/ready")
async def readiness():
    from backend.core.database import engine
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=503, detail=str(e))
