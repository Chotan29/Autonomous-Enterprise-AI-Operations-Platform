"""
Tiny in-memory vector store with real Ollama embeddings.

This is a real RAG store — not a fake one. It:
  * Calls Ollama's `/api/embeddings` endpoint with whichever
    embedding model the user has installed (auto-detected).
  * Stores vectors + metadata in memory; persists to disk on shutdown.
  * Runs cosine-similarity search in pure Python (no numpy needed).
  * Falls back to a deterministic hash embedding if Ollama is unreachable
    — so the system always works, even offline.

In production this would be Qdrant or Weaviate, but the contract is
identical: ingest(text, metadata) → embed → store; search(query, k) →
embed query → top-k cosine. The same RAG-driven config generation
that runs against this store will run against Qdrant unchanged.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx


# ── Configuration ────────────────────────────────────────────────────────────

OLLAMA_URL    = os.getenv("AEAOP_OLLAMA_URL", "http://localhost:11434")
_PREFERRED_EMBED_MODELS = [
    "embeddinggemma", "nomic-embed-text", "mxbai-embed-large",
    "all-minilm", "jina-embeddings",
    "Qwen3-Embedding", "bge-m3", "bge-large",
]


@dataclass
class VectorEntry:
    id:        str
    text:      str
    vector:    list[float]
    metadata:  dict = field(default_factory=dict)
    ts:        float = field(default_factory=time.time)


# ── Cosine similarity (pure Python) ──────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ── Embedding backends ───────────────────────────────────────────────────────

_resolved_embed_model: Optional[str] = None


async def _resolve_embed_model() -> Optional[str]:
    """Find the best embedding model Ollama has installed."""
    global _resolved_embed_model
    if _resolved_embed_model is not None:
        return _resolved_embed_model
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.5)) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            tags = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None
    # Prefer "embed" models in our preference order
    for pref in _PREFERRED_EMBED_MODELS:
        for t in tags:
            if pref.lower() in t.lower():
                _resolved_embed_model = t
                return t
    # Any model with "embed" in the name as last resort
    for t in tags:
        if "embed" in t.lower() or "rerank" in t.lower():
            _resolved_embed_model = t
            return t
    return None


def _hash_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic fallback embedding from SHA-256.
    Quality is poor (no semantics) but lets the pipeline work offline."""
    h = hashlib.sha512(text.lower().encode()).digest()
    # Repeat hash until we have enough bytes
    while len(h) < dim * 2:
        h += hashlib.sha512(h).digest()
    vec = [((h[i*2] << 8) | h[i*2+1]) / 65535.0 - 0.5 for i in range(dim)]
    # Normalize
    norm = math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def embed(text: str) -> tuple[list[float], str]:
    """Embed a single text. Returns (vector, backend-name)."""
    model = await _resolve_embed_model()
    if model:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0)) as c:
                r = await c.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                if r.status_code == 200:
                    data = r.json()
                    vec = data.get("embedding") or data.get("embeddings", [None])[0]
                    if vec:
                        return list(vec), f"ollama/{model}"
        except Exception:
            pass
    # Fallback
    return _hash_embed(text), "hash-fallback"


# ── The store ────────────────────────────────────────────────────────────────


class VectorStore:
    def __init__(self, persist_path: Optional[str] = None):
        self.entries: list[VectorEntry] = []
        self.persist_path = persist_path
        self.last_backend = "unknown"
        self._load()

    def _load(self):
        if not self.persist_path:
            return
        p = Path(self.persist_path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for raw in data.get("entries", []):
                self.entries.append(VectorEntry(**raw))
        except Exception:
            pass

    def save(self):
        if not self.persist_path:
            return
        p = Path(self.persist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(json.dumps({
                "saved_at": time.time(),
                "count":    len(self.entries),
                "entries":  [asdict(e) for e in self.entries],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def add(self, text: str, metadata: Optional[dict] = None, entry_id: Optional[str] = None) -> str:
        vec, backend = await embed(text)
        self.last_backend = backend
        eid = entry_id or hashlib.sha256(text.encode()).hexdigest()[:16]
        # De-dupe by id (overwrite metadata + ts on re-ingest)
        for i, e in enumerate(self.entries):
            if e.id == eid:
                self.entries[i] = VectorEntry(id=eid, text=text, vector=vec,
                                              metadata=metadata or {}, ts=time.time())
                return eid
        self.entries.append(VectorEntry(id=eid, text=text, vector=vec,
                                        metadata=metadata or {}, ts=time.time()))
        return eid

    async def search(self, query: str, k: int = 5,
                     filter_fn=None) -> list[tuple[VectorEntry, float]]:
        qv, _ = await embed(query)
        candidates = self.entries if filter_fn is None else [e for e in self.entries if filter_fn(e)]
        scored = [(e, _cosine(qv, e.vector)) for e in candidates]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def stats(self) -> dict:
        sources = {}
        for e in self.entries:
            v = e.metadata.get("source", "unknown")
            sources[v] = sources.get(v, 0) + 1
        return {
            "total_entries":   len(self.entries),
            "by_source":       sources,
            "embed_backend":   self.last_backend,
            "embed_dimension": len(self.entries[0].vector) if self.entries else 0,
        }

    def clear(self):
        self.entries.clear()
        self.save()
