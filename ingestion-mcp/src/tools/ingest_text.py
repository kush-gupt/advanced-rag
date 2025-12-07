"""Ingest raw text directly into the vector database."""

import time
from typing import Annotated, Any, Literal

import httpx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.services import (
    DEFAULT_COLLECTION,
    chunk_text,
    upsert_documents,
)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def ingest_text(
    text: Annotated[str, Field(description="The text content to ingest")],
    collection: Annotated[
        str | None,
        Field(description="Target Milvus collection (defaults to env DEFAULT_COLLECTION)"),
    ] = None,
    name: Annotated[
        str | None,
        Field(description="Identifier for this content (e.g., 'meeting-notes-2024-01')"),
    ] = None,
    source: Annotated[
        str | None,
        Field(description="Origin of the text (e.g., 'manual-entry', 'api-upload')"),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Tags for filtering and organization"),
    ] = None,
    chunking: Annotated[
        Literal["default", "dense", "sparse"],
        Field(description="Chunking strategy: default (200 tokens), dense (100), sparse (400)"),
    ] = "default",
    response_format: Annotated[
        Literal["concise", "detailed"],
        Field(description="Response verbosity level"),
    ] = "concise",
    ctx: Context = None,
) -> dict[str, Any]:
    """Ingest raw text directly into the vector database.

    Use this tool when you already have extracted text content and want to
    skip document parsing. Useful for API uploads, copy-pasted content, or
    text from sources that don't have a file representation.
    """
    start_time = time.time()
    stages: dict[str, int] = {}

    # Validate text is provided and has minimum length
    if not text or not text.strip():
        raise ToolError(
            "Text cannot be empty. "
            "Provide the content you want to ingest."
        )

    stripped_text = text.strip()
    if len(stripped_text) < 50:
        raise ToolError(
            f"Text too short ({len(stripped_text)} characters). "
            "Minimum is 50 characters for meaningful chunking. "
            "Provide more content or combine with other text before ingesting."
        )

    target_collection = collection or DEFAULT_COLLECTION
    content_name = name or "text-content"

    if ctx:
        await ctx.info(f"Ingesting text '{content_name}' into {target_collection}")

    # Step 1: Chunk text
    chunking_start = time.time()
    try:
        chunks = await chunk_text(
            text=stripped_text,
            chunking=chunking,
            file_name=content_name,
            file_path=None,
            mime_type="text/plain",
        )
    except ValueError as e:
        raise ToolError(str(e))
    except httpx.HTTPStatusError as e:
        raise ToolError(f"Chunker service error: {e.response.status_code}")
    except httpx.ConnectError:
        raise ToolError(
            "Cannot connect to chunker service. "
            "Verify CHUNKER_SERVICE_URL is correct and service is running."
        )
    stages["chunking_ms"] = int((time.time() - chunking_start) * 1000)

    if not chunks:
        raise ToolError(
            "Chunking produced no chunks. "
            "The text may be too short. Try 'dense' chunking for shorter content."
        )

    # Step 2: Prepare documents for upsert
    documents = []
    for i, chunk in enumerate(chunks):
        documents.append({
            "text": chunk.get("text", ""),
            "metadata": {
                "name": content_name,
                "source": source or "text-input",
                "tags": tags or [],
                "chunk_index": i,
                "mime_type": "text/plain",
            },
        })

    # Step 3: Upsert to vector gateway
    embedding_start = time.time()
    try:
        upsert_result = await upsert_documents(documents, target_collection)
    except ValueError as e:
        raise ToolError(str(e))
    except httpx.HTTPStatusError as e:
        raise ToolError(f"Vector gateway error: {e.response.status_code}")
    except httpx.ConnectError:
        raise ToolError(
            "Cannot connect to vector gateway. "
            "Verify VECTOR_GATEWAY_URL is correct and service is running."
        )
    stages["embedding_ms"] = int((time.time() - embedding_start) * 1000)

    # Build response
    chunks_created = upsert_result.get("inserted", len(documents))
    estimated_tokens = sum(len(d["text"].split()) for d in documents)
    total_time_ms = int((time.time() - start_time) * 1000)

    message = (
        f"Ingested text '{content_name}' into {target_collection} "
        f"({chunks_created} chunks, ~{estimated_tokens} tokens)"
    )

    if ctx:
        await ctx.info(message)

    result: dict[str, Any] = {
        "success": True,
        "message": message,
        "name": content_name,
        "collection": target_collection,
        "chunks_created": chunks_created,
    }

    if response_format == "detailed":
        result.update({
            "estimated_tokens": estimated_tokens,
            "processing_time_ms": total_time_ms,
            "stages": stages,
            "text_length": len(stripped_text),
        })

    return result