"""
Hybrid search: dense vector search (Qdrant) + sparse BM25 (Elasticsearch) fused with RRF.
"""
import logging
from typing import Optional

from elasticsearch import AsyncElasticsearch
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from backend.core.config import settings
from backend.services.ai_service.llm.model_router import llm

logger = logging.getLogger(__name__)
COLLECTION_NAME = "knowledge_base"


class HybridSearchEngine:
    def __init__(self):
        self._qdrant: Optional[AsyncQdrantClient] = None
        self._es: Optional[AsyncElasticsearch] = None

    @property
    def qdrant(self) -> AsyncQdrantClient:
        if self._qdrant is None:
            self._qdrant = AsyncQdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY or None,
            )
        return self._qdrant

    @property
    def es(self) -> AsyncElasticsearch:
        if self._es is None:
            kwargs = {"hosts": [settings.ELASTICSEARCH_URL]}
            if settings.ELASTICSEARCH_USERNAME:
                kwargs["http_auth"] = (settings.ELASTICSEARCH_USERNAME, settings.ELASTICSEARCH_PASSWORD)
            self._es = AsyncElasticsearch(**kwargs)
        return self._es

    async def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """Hybrid search: dense + sparse, fused with RRF."""
        try:
            query_vector = await llm.embed_single(query)
            dense_results, sparse_results = await self._parallel_search(
                query, query_vector, tenant_id, top_k * 3, filters
            )
        except Exception as exc:
            logger.error(f"Search failed: {exc}")
            return []

        fused = self._rrf_fusion(dense_results, sparse_results, k=60)
        return fused[:top_k]

    async def _parallel_search(
        self, query: str, query_vector: list[float],
        tenant_id: str, limit: int, filters: dict | None
    ):
        import asyncio
        dense_task = asyncio.create_task(
            self._dense_search(query_vector, tenant_id, limit, filters)
        )
        sparse_task = asyncio.create_task(
            self._sparse_search(query, tenant_id, limit, filters)
        )
        dense, sparse = await asyncio.gather(dense_task, sparse_task, return_exceptions=True)
        return (dense if isinstance(dense, list) else []), (sparse if isinstance(sparse, list) else [])

    async def _dense_search(
        self, vector: list[float], tenant_id: str, limit: int, filters: dict | None
    ) -> list[dict]:
        qdrant_filter = Filter(
            must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
        )
        if filters and filters.get("source_types"):
            qdrant_filter.must.append(
                Filter(
                    should=[
                        FieldCondition(key="source_type", match=MatchValue(value=st))
                        for st in filters["source_types"]
                    ]
                )
            )

        results = await self.qdrant.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )

        return [
            {
                "id": str(r.id),
                "text": r.payload.get("text", ""),
                "title": r.payload.get("title", ""),
                "source_type": r.payload.get("source_type", ""),
                "doc_id": r.payload.get("doc_id", ""),
                "chunk_index": r.payload.get("chunk_index", 0),
                "score": r.score,
                "relevance_score": r.score,
                "search_type": "dense",
            }
            for r in results
        ]

    async def _sparse_search(
        self, query: str, tenant_id: str, limit: int, filters: dict | None
    ) -> list[dict]:
        index = f"{settings.ELASTICSEARCH_INDEX_PREFIX}-rag"
        must_clauses = [
            {"term": {"tenant_id": tenant_id}},
            {"multi_match": {
                "query": query,
                "fields": ["text^2", "title^3"],
                "type": "best_fields",
            }},
        ]
        if filters and filters.get("source_types"):
            must_clauses.append({"terms": {"source_type": filters["source_types"]}})

        try:
            resp = await self.es.search(
                index=index,
                body={"query": {"bool": {"must": must_clauses}}, "size": limit},
            )
            return [
                {
                    "id": hit["_id"],
                    "text": hit["_source"].get("text", ""),
                    "title": hit["_source"].get("title", ""),
                    "source_type": hit["_source"].get("source_type", ""),
                    "doc_id": hit["_source"].get("doc_id", ""),
                    "chunk_index": hit["_source"].get("chunk_index", 0),
                    "score": hit["_score"],
                    "relevance_score": hit["_score"] / 10.0,
                    "search_type": "sparse",
                }
                for hit in resp["hits"]["hits"]
            ]
        except Exception as exc:
            logger.warning(f"ES search failed: {exc}")
            return []

    def _rrf_fusion(
        self, dense: list[dict], sparse: list[dict], k: int = 60
    ) -> list[dict]:
        """Reciprocal Rank Fusion."""
        scores: dict[str, dict] = {}

        for rank, doc in enumerate(dense):
            doc_id = doc["id"]
            if doc_id not in scores:
                scores[doc_id] = {"score": 0.0, "doc": doc}
            scores[doc_id]["score"] += 1.0 / (k + rank + 1)

        for rank, doc in enumerate(sparse):
            doc_id = doc["id"]
            if doc_id not in scores:
                scores[doc_id] = {"score": 0.0, "doc": doc}
            scores[doc_id]["score"] += 1.0 / (k + rank + 1)

        merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        result = []
        for item in merged:
            doc = item["doc"].copy()
            doc["relevance_score"] = round(item["score"], 4)
            result.append(doc)
        return result
