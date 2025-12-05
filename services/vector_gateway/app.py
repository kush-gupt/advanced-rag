from __future__ import annotations

import fnmatch
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, validator

# Import embed_texts from rag_core shared library
from rag_core import embed_texts
# Keep milvus_io from local lib (vector store specific)
from lib import milvus_io


AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
MAX_DOCS = int(os.environ.get("GATEWAY_MAX_DOCS", "10000"))
DEFAULT_BACKEND = os.environ.get("GATEWAY_BACKEND", "milvus").lower()
DEFAULT_COLLECTION = os.environ.get("MILVUS_COLLECTION", "rag_gateway")
REQUIRE_BACKEND = os.environ.get("GATEWAY_REQUIRE_BACKEND", "0").lower() in {"1", "true", "yes"}
CONFIG_PATH = os.environ.get("GATEWAY_CONFIG")
RERANK_SERVICE_URL = os.environ.get("RERANK_SERVICE_URL", "http://rerank-service:8000")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vector_gateway")
app = FastAPI(title="Vector Gateway", version="0.2.0")


@dataclass
class StoredDoc:
    doc_id: str
    text: str
    metadata: Dict[str, Any]
    vector: List[float]


class Backend(Protocol):
    name: str

    def upsert(self, docs: List[StoredDoc]) -> int:
        ...

    def search(self, query_vector: List[float], query_text: str, top_k: int) -> List[StoredDoc]:
        ...

    def count(self) -> int:
        ...


class MemoryBackend:
    name = "memory"

    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        max_docs = cfg.get("max_docs") if cfg else None
        self.max_docs = int(max_docs) if max_docs is not None else MAX_DOCS
        self.store: List[StoredDoc] = []

    def upsert(self, docs: List[StoredDoc]) -> int:
        if len(self.store) + len(docs) > self.max_docs:
            raise RuntimeError("store limit reached")
        self.store.extend(docs)
        return len(docs)

    def search(self, query_vector: List[float], query_text: str, top_k: int) -> List[StoredDoc]:
        # Memory backend ignores query_text (no BM25 support)
        scored = []
        for doc in self.store:
            if len(doc.vector) != len(query_vector):
                continue
            sim = _cosine_similarity(query_vector, doc.vector)
            # Convert cosine similarity (-1..1) to 0..1.
            norm = _normalize_score((sim + 1.0) / 2.0)
            scored.append((doc, norm))
        ranked = sorted(scored, key=lambda t: t[1], reverse=True)[:top_k]
        return [doc for doc, _ in ranked]

    def count(self) -> int:
        return len(self.store)


class MilvusBackend:
    name = "milvus"

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.milvus_io = milvus_io
        collection = cfg.get("collection") or os.environ.get("MILVUS_COLLECTION", "rag_gateway")
        dim = int(cfg.get("dim") or os.environ.get("MILVUS_DIM", 1536))
        host = cfg.get("host") or os.environ.get("MILVUS_HOST")
        port = cfg.get("port") or os.environ.get("MILVUS_PORT")
        user = cfg.get("user") or os.environ.get("MILVUS_USER")
        password = cfg.get("password") or os.environ.get("MILVUS_PASSWORD")
        if host and port:
            os.environ["MILVUS_HOST"] = str(host)
            os.environ["MILVUS_PORT"] = str(port)
        if user:
            os.environ["MILVUS_USER"] = str(user)
        if password:
            os.environ["MILVUS_PASSWORD"] = str(password)
        self.collection_name = collection
        self.collection = milvus_io.ensure_collection(collection, dim=dim)

    def upsert(self, docs: List[StoredDoc]) -> int:
        if not docs:
            return 0
        # Milvus IO expects chunk-like rows; adapt minimal fields.
        chunks = []
        vectors = []
        now_ts = int(time.time())
        for idx, doc in enumerate(docs):
            chunks.append(
                {
                    "chunk_id": doc.doc_id,
                    "file_name": doc.metadata.get("file_name", ""),
                    "file_path": doc.metadata.get("file_path", ""),
                    "page": doc.metadata.get("page", -1),
                    "section": doc.metadata.get("section", ""),
                    "mime_type": doc.metadata.get("mime_type", ""),
                    "created_at_ts": doc.metadata.get("created_at_ts", now_ts),
                    "chunk_index": doc.metadata.get("chunk_index", idx),
                    "text": doc.text,
                }
            )
            vectors.append(doc.vector)
        self.milvus_io.insert_chunks(self.collection, chunks, vectors, sparse_vectors=None)
        return len(docs)

    def search(self, query_vector: List[float], query_text: str, top_k: int) -> List[StoredDoc]:
        results = self.milvus_io.hybrid_search(
            collection=self.collection_name,
            query_vector=query_vector,
            query_text=query_text,  # BM25 keyword search
            top_k=top_k,
            overfetch=max(20, top_k * 3),
            rrf_k=60,
        )
        docs: List[StoredDoc] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity", {}) if isinstance(hit, dict) else getattr(hit, "entity", {}) or {}
            distance = hit.get("distance") if isinstance(hit, dict) else getattr(hit, "distance", None)
            similarity = None
            if isinstance(distance, (int, float)):
                similarity = 1.0 - float(distance)
            norm_score = _normalize_score(similarity)
            docs.append(
                StoredDoc(
                    doc_id=str(entity.get("chunk_id", "")),
                    text=entity.get("text", ""),
                    metadata={**entity, "distance": distance, "score": norm_score},
                    vector=[],  # vector not returned; unused for response.
                )
            )
        return docs

    def count(self) -> int:
        # Milvus IO lacks count helper; return -1 to indicate unknown.
        return -1


class UpsertDocument(BaseModel):
    doc_id: Optional[str] = Field(default=None, description="Caller-provided ID (optional)")
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator("text")
    def _validate_text(cls, v: str) -> str:
        if not v:
            raise ValueError("text must be non-empty")
        return v


class UpsertRequest(BaseModel):
    documents: List[UpsertDocument]
    collection: Optional[str] = Field(default=None, description="Target collection (creates if not exists, defaults to env MILVUS_COLLECTION)")
    namespace: Optional[str] = Field(default=None, description="Namespace (unused in memory backend)")
    model: Optional[str] = None

    @validator("documents")
    def _validate_documents(cls, v: List[UpsertDocument]) -> List[UpsertDocument]:
        if not v:
            raise ValueError("documents must be non-empty")
        return v


class UpsertResponse(BaseModel):
    inserted: int
    total: int
    backend: str
    collection: str


class SearchFilters(BaseModel):
    """Metadata filters for search."""
    file_name: Optional[str] = Field(default=None, description="Filter by exact file name")
    file_pattern: Optional[str] = Field(default=None, description="Filter by glob pattern (e.g., 'DMC-BRAKE*')")
    mime_type: Optional[str] = Field(default=None, description="Filter by MIME type")


class SearchRequest(BaseModel):
    query: str
    collection: Optional[str] = Field(default=None, description="Collection to search (defaults to env MILVUS_COLLECTION)")
    top_k: int = Field(default=5, ge=1, le=100, description="Number of results to return")
    context_window: int = Field(default=0, ge=0, le=10, description="Number of surrounding chunks to include (0=disabled)")
    filters: Optional[SearchFilters] = Field(default=None, description="Metadata filters")
    model: Optional[str] = Field(default=None, description="Embedding model override")

    @validator("top_k")
    def _validate_top_k(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("top_k must be > 0")
        return v


class SurroundingChunk(BaseModel):
    """A chunk surrounding the main search hit."""
    chunk_index: int
    text: str
    page: int = -1


class SearchHit(BaseModel):
    doc_id: str
    text: str
    score: float
    metadata: Dict[str, Any]
    surrounding_chunks: List[SurroundingChunk] = Field(default_factory=list)


class SearchResponse(BaseModel):
    hits: List[SearchHit]
    count: int
    latency_ms: int
    backend: str
    collection: str
    reranked: bool = False


def _auth_dependency(authorization: str = Header(None), x_api_key: str = Header(None)) -> None:
    if not AUTH_TOKEN:
        return
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


def _init_backend() -> Backend:
    cfg: Dict[str, Any] = {}
    if CONFIG_PATH:
        try:
            with open(CONFIG_PATH, "r") as f:
                if CONFIG_PATH.endswith((".yaml", ".yml")):
                    import yaml  # type: ignore

                    cfg = yaml.safe_load(f) or {}
                else:
                    cfg = json.load(f)
        except Exception as exc:
            logger.warning("failed to load config %s: %s", CONFIG_PATH, exc)
            cfg = {}

    backend_name = str(cfg.get("backend") or DEFAULT_BACKEND).lower()
    prefer = [backend_name]
    if backend_name != "memory":
        prefer.append("memory")

    for name in prefer:
        try:
            if name == "milvus":
                return MilvusBackend(cfg.get("milvus", {}))
            if name == "memory":
                return MemoryBackend(cfg.get("memory", {}))
        except Exception as exc:
            logger.warning("backend %s initialization failed: %s", name, exc)
            continue
    if REQUIRE_BACKEND:
        raise RuntimeError("No backend available and REQUIRE_BACKEND is set")
    return MemoryBackend(cfg.get("memory", {}))


BACKEND = _init_backend()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "backend": BACKEND.name, "count": BACKEND.count()}


@app.post("/upsert", response_model=UpsertResponse)
def upsert(request: UpsertRequest, _: None = Depends(_auth_dependency)) -> UpsertResponse:
    collection = request.collection or DEFAULT_COLLECTION

    if BACKEND.name == "memory" and BACKEND.count() + len(request.documents) > MAX_DOCS:
        raise HTTPException(status_code=400, detail="store limit reached")
    texts = [d.text for d in request.documents]
    vectors = embed_texts(texts, model=request.model, prefer_service=True)
    if len(vectors) != len(texts):
        raise HTTPException(status_code=500, detail="embedding failed")

    # For Milvus backend, use collection-specific upsert
    if BACKEND.name == "milvus":
        try:
            # Get or create collection (never drops existing data)
            handle = milvus_io.get_or_create_collection(collection)

            # Build chunks for insertion
            chunks = []
            now_ts = int(time.time())
            for idx, doc in enumerate(request.documents):
                doc_id = doc.doc_id or f"doc-{idx}-{now_ts}"
                chunks.append({
                    "chunk_id": doc_id,
                    "file_name": doc.metadata.get("file_name", ""),
                    "file_path": doc.metadata.get("file_path", ""),
                    "page": doc.metadata.get("page", -1),
                    "section": doc.metadata.get("section", ""),
                    "mime_type": doc.metadata.get("mime_type", ""),
                    "created_at_ts": doc.metadata.get("created_at_ts", now_ts),
                    "chunk_index": doc.metadata.get("chunk_index", idx),
                    "text": doc.text,
                })

            # Insert into collection
            milvus_io.insert_chunks(handle, chunks, vectors, sparse_vectors=None)
            inserted = len(chunks)
            logger.info("upserted %d docs to collection=%s backend=%s", inserted, collection, BACKEND.name)
            return UpsertResponse(inserted=inserted, total=-1, backend=BACKEND.name, collection=collection)

        except Exception as exc:
            logger.error("upsert to collection=%s failed: %s", collection, exc)
            raise HTTPException(status_code=500, detail=f"Upsert failed: {exc}")

    # Memory backend fallback (doesn't support collections)
    inserted = 0
    for doc, vec in zip(request.documents, vectors):
        doc_id = doc.doc_id or f"doc-{BACKEND.count()+1}"
        stored = StoredDoc(doc_id=doc_id, text=doc.text, metadata=doc.metadata, vector=vec)
        BACKEND.upsert([stored])
        inserted += 1
    logger.info("upserted %d docs backend=%s", inserted, BACKEND.name)
    return UpsertResponse(inserted=inserted, total=BACKEND.count(), backend=BACKEND.name, collection=collection)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalize_score(val: Optional[float]) -> float:
    if val is None:
        return 0.0
    try:
        return max(0.0, min(1.0, float(val)))
    except Exception:
        return 0.0


def _rerank_documents(query: str, documents: List[str], top_k: Optional[int] = None) -> tuple[List[int], bool]:
    """Call rerank service. Returns (indices, success). Falls back to original order on error."""
    if not documents:
        return [], True
    try:
        with httpx.Client(timeout=30.0) as client:
            payload = {"query": query, "documents": documents}
            if top_k is not None:
                payload["top_k"] = top_k
            resp = client.post(f"{RERANK_SERVICE_URL}/rerank", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("indices", list(range(len(documents)))), True
    except Exception as exc:
        logger.warning("rerank service failed, returning unranked: %s", exc)
        return list(range(len(documents))), False


def _apply_filters(hits: List[Dict[str, Any]], filters: Optional[SearchFilters]) -> List[Dict[str, Any]]:
    """Apply metadata filters to search hits."""
    if not filters:
        return hits

    filtered = []
    for hit in hits:
        metadata = hit.get("metadata", {})
        # The entity data may be nested under metadata.entity (from Milvus) or directly in metadata
        entity = metadata.get("entity", metadata)
        file_name = entity.get("file_name", "") or metadata.get("file_name", "")
        mime_type = entity.get("mime_type", "") or metadata.get("mime_type", "")

        # file_name exact match
        if filters.file_name and file_name != filters.file_name:
            continue

        # file_pattern glob match
        if filters.file_pattern and not fnmatch.fnmatch(file_name, filters.file_pattern):
            continue

        # mime_type exact match
        if filters.mime_type and mime_type != filters.mime_type:
            continue

        filtered.append(hit)

    return filtered


def _get_surrounding_chunks(
    collection: str, file_name: str, chunk_index: int, window: int
) -> List[SurroundingChunk]:
    """Fetch surrounding chunks using milvus_io helper."""
    if window <= 0:
        return []
    try:
        chunks = milvus_io.get_context_chunks(collection, file_name, chunk_index, window)
        return [
            SurroundingChunk(
                chunk_index=c.get("chunk_index", 0),
                text=c.get("text", ""),
                page=c.get("page", -1),
            )
            for c in chunks
            if c.get("chunk_index") != chunk_index  # exclude the hit itself
        ]
    except Exception as exc:
        logger.warning("failed to get surrounding chunks: %s", exc)
        return []


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, _: None = Depends(_auth_dependency)) -> SearchResponse:
    start = time.time()
    collection = request.collection or DEFAULT_COLLECTION

    # Check if we're using Milvus backend
    if BACKEND.name != "milvus":
        # Memory backend - use simple search
        if BACKEND.count() == 0:
            return SearchResponse(
                hits=[], count=0, latency_ms=0, backend=BACKEND.name,
                collection=collection, reranked=False
            )
        qvec = embed_texts([request.query], model=request.model, prefer_service=True)[0]
        docs = BACKEND.search(qvec, query_text=request.query, top_k=request.top_k)
        scored_hits: List[SearchHit] = []
        for doc in docs:
            score = _cosine_similarity(qvec, doc.vector) if doc.vector else doc.metadata.get("score", 0.0)
            score = _normalize_score(score)
            scored_hits.append(SearchHit(
                doc_id=doc.doc_id, text=doc.text, metadata=doc.metadata, score=score
            ))
        latency_ms = int((time.time() - start) * 1000)
        return SearchResponse(
            hits=scored_hits, count=len(scored_hits), latency_ms=latency_ms,
            backend=BACKEND.name, collection=collection, reranked=False
        )

    # Milvus backend - use enhanced search
    try:
        # Embed the query
        qvec = embed_texts([request.query], model=request.model, prefer_service=True)[0]

        # Overfetch for filtering and reranking
        overfetch = max(request.top_k * 4, 50) if request.filters else request.top_k * 2

        # Hybrid search
        results = milvus_io.hybrid_search(
            collection=collection,
            query_vector=qvec,
            query_text=request.query,
            top_k=overfetch,
            overfetch=overfetch,
            rrf_k=60,
        )

        # Convert to hit dicts
        raw_hits: List[Dict[str, Any]] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity", {}) if isinstance(hit, dict) else getattr(hit, "entity", {}) or {}
            distance = hit.get("distance") if isinstance(hit, dict) else getattr(hit, "distance", None)
            score = 1.0 - float(distance) if isinstance(distance, (int, float)) else 0.0
            raw_hits.append({
                "doc_id": str(entity.get("chunk_id", "")),
                "text": entity.get("text", ""),
                "score": _normalize_score(score),
                "metadata": {**entity, "distance": distance, "score": _normalize_score(score)},
            })

        # Apply filters
        filtered_hits = _apply_filters(raw_hits, request.filters)

        # Rerank (always on, graceful fallback)
        reranked = False
        if filtered_hits:
            texts = [h["text"] for h in filtered_hits]
            rerank_indices, rerank_success = _rerank_documents(request.query, texts, top_k=request.top_k)
            reranked = rerank_success
            if rerank_success:
                filtered_hits = [filtered_hits[i] for i in rerank_indices if i < len(filtered_hits)]

        # Limit to top_k
        filtered_hits = filtered_hits[:request.top_k]

        # Build response with surrounding chunks
        scored_hits: List[SearchHit] = []
        for hit in filtered_hits:
            surrounding = []
            if request.context_window > 0:
                metadata = hit["metadata"]
                entity = metadata.get("entity", metadata)
                file_name = entity.get("file_name", "") or metadata.get("file_name", "")
                chunk_index = entity.get("chunk_index", 0) if entity.get("chunk_index") is not None else metadata.get("chunk_index", 0)
                if file_name:
                    surrounding = _get_surrounding_chunks(
                        collection, file_name, chunk_index, request.context_window
                    )

            scored_hits.append(SearchHit(
                doc_id=hit["doc_id"],
                text=hit["text"],
                score=hit["score"],
                metadata=hit["metadata"],
                surrounding_chunks=surrounding,
            ))

        latency_ms = int((time.time() - start) * 1000)
        logger.info(
            "search collection=%s query=%r top_k=%d filters=%s context_window=%d reranked=%s hits=%d latency_ms=%d",
            collection, request.query[:50], request.top_k, bool(request.filters),
            request.context_window, reranked, len(scored_hits), latency_ms
        )

        return SearchResponse(
            hits=scored_hits,
            count=len(scored_hits),
            latency_ms=latency_ms,
            backend="milvus",
            collection=collection,
            reranked=reranked,
        )

    except Exception as exc:
        logger.error("search failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}")


# ============================================================================
# Collection Discovery Endpoints
# ============================================================================


class CollectionInfo(BaseModel):
    """Basic collection information."""
    name: str


class CollectionStats(BaseModel):
    """Detailed collection statistics."""
    name: str
    row_count: int
    file_names: List[str]
    mime_types: List[str]


class CollectionsResponse(BaseModel):
    """Response for GET /collections."""
    collections: List[str]
    count: int


class CollectionStatsResponse(BaseModel):
    """Response for GET /collections/{name}/stats."""
    stats: CollectionStats


@app.get("/collections", response_model=CollectionsResponse)
def list_collections(_: None = Depends(_auth_dependency)) -> CollectionsResponse:
    """List all available Milvus collections."""
    if BACKEND.name != "milvus":
        return CollectionsResponse(collections=[], count=0)

    try:
        collections = milvus_io.list_collections()
        logger.info("list_collections found %d collections", len(collections))
        return CollectionsResponse(collections=collections, count=len(collections))
    except Exception as exc:
        logger.error("list_collections failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to list collections: {exc}")


@app.get("/collections/{collection_name}/stats", response_model=CollectionStatsResponse)
def get_collection_stats(
    collection_name: str, _: None = Depends(_auth_dependency)
) -> CollectionStatsResponse:
    """Get statistics for a specific collection."""
    if BACKEND.name != "milvus":
        raise HTTPException(status_code=400, detail="Stats only available for Milvus backend")

    try:
        stats = milvus_io.get_collection_stats(collection_name)
        if "error" in stats:
            raise HTTPException(status_code=404, detail=stats["error"])

        logger.info(
            "get_collection_stats collection=%s rows=%d files=%d",
            collection_name, stats.get("row_count", 0), len(stats.get("file_names", []))
        )
        return CollectionStatsResponse(
            stats=CollectionStats(
                name=stats["name"],
                row_count=stats.get("row_count", 0),
                file_names=stats.get("file_names", []),
                mime_types=stats.get("mime_types", []),
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_collection_stats failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to get collection stats: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8005")))
