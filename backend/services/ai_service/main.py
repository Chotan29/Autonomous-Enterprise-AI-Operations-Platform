from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, AsyncIterator

from backend.core.config import settings
from backend.shared.middleware.audit_middleware import AuditMiddleware
from backend.shared.middleware.tenant_middleware import TenantMiddleware
from backend.services.ai_service.llm.model_router import llm
from backend.services.auth_service.deps import AuthRequired

app = FastAPI(
    title="AEAOP AI Service",
    description="Local LLM inference and AI analysis engine",
    version=settings.APP_VERSION,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)
app.add_middleware(AuditMiddleware)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    stream: bool = False


class AnalyzeAlertRequest(BaseModel):
    alert_data: dict
    device_info: Optional[dict] = None
    similar_incidents: Optional[list] = None
    rag_context: Optional[list] = None


class AnalyzeIncidentRequest(BaseModel):
    incident_data: dict
    events: Optional[list] = None
    timeline: Optional[list] = None


class EmbedRequest(BaseModel):
    texts: list[str] | str
    model: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/v1/ai/chat")
async def chat(body: ChatRequest, current_user: AuthRequired):
    if body.stream:
        async def stream_gen() -> AsyncIterator[bytes]:
            async for chunk in llm.generate_stream(
                prompt=body.message,
                system_prompt=body.system_prompt,
                model=body.model,
                temperature=body.temperature,
            ):
                yield f"data: {chunk}\n\n".encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(stream_gen(), media_type="text/event-stream")

    response = await llm.generate(
        prompt=body.message,
        system_prompt=body.system_prompt,
        model=body.model,
        temperature=body.temperature,
    )
    return {
        "content": response.content,
        "model": response.model,
        "tokens_used": response.tokens_used,
    }


@app.post("/api/v1/ai/analyze/alert")
async def analyze_alert(body: AnalyzeAlertRequest, current_user: AuthRequired):
    """AI Root Cause Analysis for a network/server alert."""
    from backend.services.ai_service.prompts.noc_prompts import NOC_RCA_SYSTEM
    import json

    prompt = f"""Analyze this alert and provide root cause analysis.

ALERT DATA:
{json.dumps(body.alert_data, indent=2, default=str)}

DEVICE INFO:
{json.dumps(body.device_info or {}, indent=2, default=str)}

SIMILAR PAST INCIDENTS:
{json.dumps(body.similar_incidents or [], indent=2, default=str)}

KNOWLEDGE BASE CONTEXT:
{json.dumps(body.rag_context or [], indent=2, default=str)}

Provide comprehensive root cause analysis as JSON."""

    response = await llm.generate(
        prompt=prompt,
        system_prompt=NOC_RCA_SYSTEM,
        temperature=0.05,  # Very deterministic for RCA
    )

    # Try to parse JSON response
    try:
        import re
        json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
        if json_match:
            rca_data = json.loads(json_match.group())
        else:
            rca_data = {"root_cause": response.content, "confidence_pct": 50}
    except Exception:
        rca_data = {"root_cause": response.content, "confidence_pct": 50}

    return {
        "rca": rca_data,
        "raw_response": response.content,
        "model": response.model,
        "tokens_used": response.tokens_used,
    }


@app.post("/api/v1/ai/analyze/incident")
async def analyze_incident(body: AnalyzeIncidentRequest, current_user: AuthRequired):
    """AI analysis for a security incident."""
    from backend.services.ai_service.prompts.soc_prompts import SOC_THREAT_SYSTEM
    import json

    prompt = f"""Analyze this security incident.

INCIDENT DATA:
{json.dumps(body.incident_data, indent=2, default=str)}

RELATED EVENTS:
{json.dumps(body.events or [], indent=2, default=str)}

TIMELINE:
{json.dumps(body.timeline or [], indent=2, default=str)}

Provide threat analysis as JSON."""

    response = await llm.generate(
        prompt=prompt,
        system_prompt=SOC_THREAT_SYSTEM,
        temperature=0.05,
    )

    try:
        import re
        json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
        analysis = json.loads(json_match.group()) if json_match else {}
    except Exception:
        analysis = {}

    return {
        "analysis": analysis,
        "raw_response": response.content,
        "model": response.model,
    }


@app.post("/api/v1/ai/embed")
async def embed(body: EmbedRequest, current_user: AuthRequired):
    embeddings = await llm.embed(body.texts, model=body.model)
    return {
        "embeddings": embeddings,
        "model": body.model or settings.LLM_EMBEDDING_MODEL,
        "count": len(embeddings),
    }


@app.post("/api/v1/ai/generate/report")
async def generate_report(
    report_type: str,
    data: dict,
    current_user: AuthRequired,
):
    """Generate an AI-written report section."""
    from backend.services.ai_service.prompts.noc_prompts import NOC_BANDWIDTH_ANALYSIS_SYSTEM
    import json

    system = NOC_BANDWIDTH_ANALYSIS_SYSTEM
    prompt = f"""Generate a {report_type} report based on this data:\n{json.dumps(data, indent=2, default=str)}"""

    response = await llm.generate(prompt=prompt, system_prompt=system)
    return {"content": response.content, "tokens_used": response.tokens_used}


@app.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "ai"}


@app.get("/health/ready")
async def readiness():
    try:
        # Quick model check
        response = await llm.generate("ping", max_tokens=5, temperature=0)
        return {"status": "ready", "model": response.model}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"AI service not ready: {e}")
