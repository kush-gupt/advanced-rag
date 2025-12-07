"""Ingest a document file into the vector database."""

import mimetypes
import os
import time
from typing import Annotated, Any, Literal

import httpx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.services import (
    DEFAULT_COLLECTION,
    SUPPORTED_EXTENSIONS,
    chunk_text,
    parse_document,
    upsert_documents,
)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def ingest_document(
    file_path: Annotated[str, Field(description="Absolute path to the file to ingest")],
    collection: Annotated[
        str | None,
        Field(description="Target Milvus collection (defaults to env DEFAULT_COLLECTION)"),
    ] = None,
    source: Annotated[
        str | None,
        Field(description="Source identifier for tracking origin of document"),
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
    """Ingest a document file into the vector database.

    Parses the document, chunks the text, generates embeddings, and stores
    in the specified Milvus collection.

    Supported file types: PDF, DOCX, TXT, MD, HTML
    """
    start_time = time.time()
    stages: dict[str, int] = {}

    # Validate file path is absolute
    if not os.path.isabs(file_path):
        raise ToolError(
            f"Path must be absolute: {file_path}. "
            "Provide the full path starting with /."
        )

    # Validate file exists
    if not os.path.exists(file_path):
        raise ToolError(
            f"File not found: {file_path}. "
            "Verify the file exists and the path is correct. "
            "Use ingest_from_url if the document is hosted remotely."
        )

    # Validate file type
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ToolError(
            f"Unsupported file type: {ext}. "
            f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}. "
            "Convert to a supported format or use ingest_text with pre-extracted content."
        )

    file_name = os.path.basename(file_path)
    target_collection = collection or DEFAULT_COLLECTION
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"

    if ctx:
        await ctx.info(f"Ingesting {file_name} into {target_collection}")

    # Step 1: Read file
    try:
        with open(file_path, "rb") as f:
            content = f.read()
    except PermissionError:
        raise ToolError(f"Permission denied reading {file_path}. Check file permissions.")
    except Exception as e:
        raise ToolError(f"Failed to read file: {e}")

    # Step 2: Parse document (skip for plain text)
    parsing_start = time.time()
    if ext in {".txt", ".md"}:
        text = content.decode("utf-8", errors="replace")
    else:
        try:
            text = await parse_document(file_path, content, mime_type)
        except ValueError as e:
            raise ToolError(str(e))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise ToolError(
                    "Document parsing failed: Invalid format. "
                    "The file may be corrupted or password-protected."
                )
            raise ToolError(f"Docling service error: {e.response.status_code}")
        except httpx.ConnectError:
            raise ToolError(
                "Cannot connect to Docling service. "
                "Verify DOCLING_SERVICE_URL is correct and service is running."
            )
    stages["parsing_ms"] = int((time.time() - parsing_start) * 1000)

    # Validate extracted text
    if not text or len(text.strip()) < 50:
        raise ToolError(
            f"Document has insufficient text ({len(text.strip()) if text else 0} chars). "
            "The file may be empty, an image-only PDF, or corrupted."
        )

    # Step 3: Chunk text
    chunking_start = time.time()
    try:
        chunks = await chunk_text(
            text=text,
            chunking=chunking,
            file_name=file_name,
            file_path=file_path,
            mime_type=mime_type,
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
            "The document may be too short. Try 'dense' chunking for shorter documents."
        )

    # Step 4: Prepare documents for upsert
    documents = []
    for i, chunk in enumerate(chunks):
        documents.append({
            "text": chunk.get("text", ""),
            "metadata": {
                "file_name": file_name,
                "file_path": file_path,
                "source": source or file_name,
                "tags": tags or [],
                "chunk_index": i,
                "page": chunk.get("page", -1),
                "section": chunk.get("section", ""),
                "mime_type": mime_type,
            },
        })

    # Step 5: Upsert to vector gateway
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
        f"Successfully ingested {file_name} into {target_collection} "
        f"({chunks_created} chunks, ~{estimated_tokens} tokens)"
    )

    if ctx:
        await ctx.info(message)

    result: dict[str, Any] = {
        "success": True,
        "message": message,
        "file_name": file_name,
        "collection": target_collection,
        "chunks_created": chunks_created,
    }

    if response_format == "detailed":
        result.update({
            "estimated_tokens": estimated_tokens,
            "processing_time_ms": total_time_ms,
            "stages": stages,
        })

    return result
