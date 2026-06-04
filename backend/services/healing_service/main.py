"""
Healing Service — manages autonomous remediation actions and approval workflows.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.database import create_all_tables
from backend.core.kafka_client import consume_forever, Topics
from backend.shared.middleware.tenant_middleware import TenantMiddleware
from backend.services.healing_service.api.v1.routers import actions, approvals
from backend.services.healing_service.workers.action_worker import ActionWorker


_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    worker = ActionWorker()
    _tasks.append(
        asyncio.create_task(consume_forever([Topics.HEALING_TASKS], worker.handle_message))
    )
    yield
    for t in _tasks:
        t.cancel()


app = FastAPI(
    title="AEAOP Healing Service",
    description="Autonomous infrastructure remediation engine",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)

app.include_router(actions.router,   prefix="/api/v1/healing", tags=["Healing Actions"])
app.include_router(approvals.router, prefix="/api/v1/healing", tags=["Approvals"])


@app.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "healing"}
