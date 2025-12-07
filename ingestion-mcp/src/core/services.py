"""External service clients for ingestion pipeline."""

import os
from typing import Any

import httpx

# Service URLs from environment
DOCLING_SERVICE_URL = os.environ.get("DOCLING_SERVICE_URL", "")
CHUNKER_SERVICE_URL = os.environ.get("CHUNKER_SERVICE_URL", "")
VECTOR_GATEWAY_URL = os.environ.get("VECTOR_GATEWAY_URL", "")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")
DEFAULT_COLLECTION = os.environ.get("DEFAULT_COLLECTION", "rag_gateway")

# Chunking presets
CHUNKING_PRESETS = {
    "default": {"window_size": 200, "overlap": 40, "mode": "tokens"},
    "dense": {"window_size": 100, "overlap": 30, "mode": "tokens"},
    "sparse": {"window_size": 400, "overlap": 60, "mode": "tokens"},
}

# Supported file types
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm"}

# HTTP client timeout
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def get_auth_headers() -> dict[str, str]:
    """Get authorization headers if AUTH_TOKEN is set."""
    if AUTH_TOKEN:
        return {"Authorization": f"Bearer {AUTH_TOKEN}"}
    return {}


async def parse_document(file_path: str, content: bytes, mime_type: str) -> str:
    """Parse document using Docling service.

    Args:
        file_path: Path to the file (for metadata)
        content: Raw file content bytes
        mime_type: MIME type of the file

    Returns:
        Extracted text from document

    Raises:
        httpx.HTTPStatusError: If Docling service returns error
        ValueError: If Docling service is not configured
    """
    if not DOCLING_SERVICE_URL:
        raise ValueError(
            "DOCLING_SERVICE_URL not configured. "
            "Set this environment variable or use ingest_text for pre-extracted content."
        )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Docling expects multipart form data
        files = {"file": (os.path.basename(file_path), content, mime_type)}
        response = await client.post(
            f"{DOCLING_SERVICE_URL}/convert",
            files=files,
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        result = response.json()

        # Docling returns {"text": "...", ...}
        return result.get("text", "")


async def chunk_text(
    text: str,
    chunking: str,
    file_name: str = "",
    file_path: str = "",
    mime_type: str = "text/plain",
) -> list[dict[str, Any]]:
    """Chunk text using chunker service.

    Args:
        text: Text to chunk
        chunking: Chunking preset name (default, dense, sparse)
        file_name: Original file name for metadata
        file_path: Original file path for metadata
        mime_type: MIME type for metadata

    Returns:
        List of chunk dictionaries with text and metadata

    Raises:
        httpx.HTTPStatusError: If chunker service returns error
        ValueError: If chunker service is not configured
    """
    if not CHUNKER_SERVICE_URL:
        raise ValueError(
            "CHUNKER_SERVICE_URL not configured. "
            "Set this environment variable to enable chunking."
        )

    # Get chunking plan from preset
    plan = CHUNKING_PRESETS.get(chunking, CHUNKING_PRESETS["default"])

    payload = {
        "text": text,
        "plan": plan,
        "meta": {
            "file_name": file_name,
            "file_path": file_path,
            "mime_type": mime_type,
        },
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{CHUNKER_SERVICE_URL}/chunk",
            json=payload,
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def upsert_documents(
    documents: list[dict[str, Any]],
    collection: str,
) -> dict[str, Any]:
    """Upsert documents to vector gateway.

    Args:
        documents: List of documents with text and metadata
        collection: Target Milvus collection name

    Returns:
        Upsert response from vector gateway

    Raises:
        httpx.HTTPStatusError: If vector gateway returns error
        ValueError: If vector gateway is not configured
    """
    if not VECTOR_GATEWAY_URL:
        raise ValueError(
            "VECTOR_GATEWAY_URL not configured. "
            "Set this environment variable to enable storage."
        )

    payload = {
        "documents": documents,
        "collection": collection,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{VECTOR_GATEWAY_URL}/upsert",
            json=payload,
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def list_collections() -> list[str]:
    """List all collections from vector gateway.

    Returns:
        List of collection names

    Raises:
        httpx.HTTPStatusError: If vector gateway returns error
        ValueError: If vector gateway is not configured
    """
    if not VECTOR_GATEWAY_URL:
        raise ValueError(
            "VECTOR_GATEWAY_URL not configured. "
            "Set this environment variable."
        )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            f"{VECTOR_GATEWAY_URL}/collections",
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        result = response.json()
        return result.get("collections", [])


async def get_collection_stats(collection: str) -> dict[str, Any]:
    """Get stats for a specific collection.

    Args:
        collection: Collection name

    Returns:
        Collection statistics

    Raises:
        httpx.HTTPStatusError: If vector gateway returns error
        ValueError: If vector gateway is not configured
    """
    if not VECTOR_GATEWAY_URL:
        raise ValueError(
            "VECTOR_GATEWAY_URL not configured. "
            "Set this environment variable."
        )

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            f"{VECTOR_GATEWAY_URL}/collections/{collection}/stats",
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        result = response.json()
        return result.get("stats", {})
