import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.database import create_all_tables
from backend.core.kafka_client import consume_forever, Topics
from backend.shared.middleware.audit_middleware import AuditMiddleware
from backend.shared.middleware.tenant_middleware import TenantMiddleware
from backend.services.soc_service.api.v1.routers import siem, incidents, threats, ueba
from backend.services.soc_service.engines.event_processor import EventProcessor


_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    processor = EventProcessor()
    # Consume SIEM events from Kafka
    _tasks.append(
        asyncio.create_task(
            consume_forever([Topics.SIEM_EVENTS, Topics.ALERTS_RAW], processor.handle_event)
        )
    )
    yield
    for t in _tasks:
        t.cancel()


app = FastAPI(
    title="AEAOP SOC Service",
    description="AI-Powered Security Operations Center",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)
app.add_middleware(AuditMiddleware)

app.include_router(siem.router,       prefix="/api/v1/soc",       tags=["SIEM"])
app.include_router(incidents.router,  prefix="/api/v1/soc",       tags=["Incidents"])
app.include_router(threats.router,    prefix="/api/v1/soc",       tags=["Threats"])
app.include_router(ueba.router,       prefix="/api/v1/soc/ueba",  tags=["UEBA"])


@app.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "soc"}

@app.get("/health/ready")
async def readiness():
    return {"status": "ready"}
