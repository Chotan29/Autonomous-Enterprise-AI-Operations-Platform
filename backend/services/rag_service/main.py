from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import io

from backend.core.config import settings
from backend.shared.middleware.tenant_middleware import TenantMiddleware
from backend.services.auth_service.deps import AuthRequired
from backend.services.rag_service.ingestion.pipeline import IngestionPipeline
from backend.services.rag_service.retrieval.hybrid_search import HybridSearchEngine

app = FastAPI(
    title="AEAOP RAG Service",
    description="Enterprise Retrieval-Augmented Generation",
    version=settings.APP_VERSION,
    docs_url="/docs",
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)

ingestion = IngestionPipeline()
search_engine = HybridSearchEngine()


class QueryRequest(BaseModel):
    question: str
    context: dict = {}
    filters: dict = {}
    top_k: int = 5


class QueryResponse(BaseModel):
    answer: str
    confidence: float
    sources: list[dict]
    related_incidents: list[dict]
    model: str
    tokens_used: int


@app.post("/api/v1/rag/query", response_model=QueryResponse)
async def query_rag(body: QueryRequest, current_user: AuthRequired):
    """Answer questions using enterprise knowledge base."""
    results = await search_engine.search(
        query=body.question,
        tenant_id=str(current_user.tenant_id),
        top_k=body.top_k,
        filters=body.filters,
    )

    if not results:
        return QueryResponse(
            answer="No relevant documentation found for this query.",
            confidence=0.0,
            sources=[], related_incidents=[], model="none", tokens_used=0,
        )

    context = "\n\n".join([
        f"Source: {r.get('title', 'Unknown')}\n{r.get('text', '')[:800]}"
        for r in results[:5]
    ])

    from backend.services.ai_service.llm.model_router import llm

    prompt = f"""Answer the following question using ONLY the provided documentation.
If the answer is not in the documentation, say so clearly.

QUESTION: {body.question}

DOCUMENTATION:
{context}

Provide a clear, specific, actionable answer. Reference the source documentation."""

    response = await llm.generate(prompt=prompt, temperature=0.1)

    return QueryResponse(
        answer=response.content,
        confidence=min(1.0, (results[0].get("relevance_score", 0.5) if results else 0.0)),
        sources=[
            {
                "title": r.get("title"),
                "source_type": r.get("source_type"),
                "relevance_score": r.get("relevance_score"),
                "chunk": r.get("text", "")[:300],
            }
            for r in results[:5]
        ],
        related_incidents=[],
        model=response.model,
        tokens_used=response.tokens_used,
    )


@app.post("/api/v1/rag/documents/ingest")
async def ingest_document(
    current_user: AuthRequired,
    file: UploadFile = File(...),
    source_type: str = "sop",
    title: Optional[str] = None,
):
    """Upload and index a document into the RAG knowledge base."""
    current_user.require("knowledge_base", "write")

    content = await file.read()
    doc_title = title or file.filename or "Untitled"

    job_id = await ingestion.ingest_file(
        content=content,
        filename=file.filename or "document",
        title=doc_title,
        source_type=source_type,
        tenant_id=str(current_user.tenant_id),
    )

    return {"message": "Document ingestion started", "job_id": job_id, "title": doc_title}


@app.get("/api/v1/rag/documents")
async def list_documents(current_user: AuthRequired):
    current_user.require("knowledge_base", "read")
    from backend.core.database import get_db_context
    from backend.shared.models.knowledge import KnowledgeDocument
    from sqlalchemy import select
    import uuid

    async with get_db_context() as db:
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.tenant_id == current_user.tenant_id)
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(100)
        )
        docs = result.scalars().all()
        return [
            {
                "id": str(d.id),
                "title": d.title,
                "source_type": d.source_type,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "indexed_at": d.indexed_at,
                "tags": d.tags,
            }
            for d in docs
        ]


@app.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "rag"}
