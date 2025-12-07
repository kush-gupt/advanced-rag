"""Fetch and ingest content from a URL."""

import re
import ssl
import time
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

import httpx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.services import (
    DEFAULT_COLLECTION,
    TIMEOUT,
    chunk_text,
    parse_document,
    upsert_documents,
)

# Content type mappings
CONTENT_TYPE_MAP = {
    "application/pdf": ("PDF", "document"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("DOCX", "document"),
    "application/msword": ("DOC", "document"),
    "text/html": ("HTML", "html"),
    "text/plain": ("TXT", "text"),
    "text/markdown": ("MD", "text"),
}


def extract_text_from_html(html_content: str) -> str:
    """Simple HTML text extraction without external dependencies."""
    # Remove scripts and styles
    text = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text)
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    return text.strip()


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": True,  # Accesses external URLs
    }
)
async def ingest_from_url(
    url: Annotated[str, Field(description="URL to fetch and ingest")],
    collection: Annotated[
        str | None,
        Field(description="Target Milvus collection (defaults to env DEFAULT_COLLECTION)"),
    ] = None,
    source: Annotated[
        str | None,
        Field(description="Source identifier (defaults to URL domain)"),
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
    """Fetch and ingest content from a URL.

    Downloads the document from the URL, detects content type, parses it,
    and stores in the vector database. Useful for PDFs and documents
    hosted remotely that agents cannot fetch directly.
    """
    start_time = time.time()
    stages: dict[str, int] = {}

    # Validate URL format
    if not url or not url.strip():
        raise ToolError(
            "URL cannot be empty. "
            "Provide a valid HTTP or HTTPS URL."
        )

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ToolError(
            f"Invalid URL scheme: {parsed.scheme}. "
            "Only HTTP and HTTPS URLs are supported."
        )

    if not parsed.netloc:
        raise ToolError(
            f"Invalid URL: {url}. "
            "URL must include a domain (e.g., https://example.com/doc.pdf)."
        )

    target_collection = collection or DEFAULT_COLLECTION
    url_source = source or parsed.netloc

    if ctx:
        await ctx.info(f"Fetching content from {url}")

    # Step 1: Fetch URL content
    fetch_start = time.time()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
            content_type_header = response.headers.get("content-type", "").lower()
    except httpx.HTTPStatusError as e:
        raise ToolError(
            f"URL fetch failed: {e.response.status_code} {e.response.reason_phrase}. "
            "Verify the URL is correct and publicly accessible."
        )
    except httpx.ConnectError:
        raise ToolError(
            f"Cannot connect to {parsed.netloc}. "
            "Verify the URL is correct and the server is reachable."
        )
    except ssl.SSLError:
        raise ToolError(
            "URL fetch failed: SSL certificate verification failed. "
            "The server's SSL certificate is invalid. Contact the site administrator."
        )
    except httpx.TimeoutException:
        raise ToolError(
            f"URL fetch timed out for {url}. "
            "The server took too long to respond. Try again later."
        )
    stages["fetch_ms"] = int((time.time() - fetch_start) * 1000)

    # Step 2: Detect content type
    content_type_key = content_type_header.split(";")[0].strip()
    type_info = CONTENT_TYPE_MAP.get(content_type_key)

    if not type_info:
        # Try to infer from URL extension
        path_lower = parsed.path.lower()
        if path_lower.endswith(".pdf"):
            type_info = ("PDF", "document")
            content_type_key = "application/pdf"
        elif path_lower.endswith(".docx"):
            type_info = ("DOCX", "document")
            content_type_key = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif path_lower.endswith(".html") or path_lower.endswith(".htm"):
            type_info = ("HTML", "html")
            content_type_key = "text/html"
        elif path_lower.endswith(".txt"):
            type_info = ("TXT", "text")
            content_type_key = "text/plain"
        elif path_lower.endswith(".md"):
            type_info = ("MD", "text")
            content_type_key = "text/markdown"
        else:
            raise ToolError(
                f"Unsupported content type: {content_type_header}. "
                "Supported types: PDF, DOCX, HTML, TXT, MD."
            )

    content_type_name, processing_mode = type_info

    # Step 3: Extract text based on content type
    parsing_start = time.time()
    if processing_mode == "text":
        # Plain text - decode directly
        text = content.decode("utf-8", errors="replace")
    elif processing_mode == "html":
        # HTML - extract text
        html_content = content.decode("utf-8", errors="replace")
        text = extract_text_from_html(html_content)
    else:
        # PDF/DOCX - use Docling
        try:
            text = await parse_document(
                file_path=url,  # Use URL as file path for metadata
                content=content,
                mime_type=content_type_key,
            )
        except ValueError as e:
            raise ToolError(str(e))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise ToolError(
                    f"Document parsing failed: Invalid {content_type_name} format. "
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
            f"URL content has insufficient text ({len(text.strip()) if text else 0} chars). "
            "The page may be empty, require authentication, or be primarily images."
        )

    # Step 4: Chunk text
    chunking_start = time.time()
    try:
        chunks = await chunk_text(
            text=text,
            chunking=chunking,
            file_name=url,
            file_path=url,
            mime_type=content_type_key,
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
            "The content may be too short. Try 'dense' chunking."
        )

    # Step 5: Prepare documents for upsert
    documents = []
    for i, chunk in enumerate(chunks):
        documents.append({
            "text": chunk.get("text", ""),
            "metadata": {
                "url": url,
                "source": url_source,
                "tags": tags or [],
                "chunk_index": i,
                "content_type": content_type_name,
                "mime_type": content_type_key,
            },
        })

    # Step 6: Upsert to vector gateway
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
        f"Ingested {url} into {target_collection} "
        f"({chunks_created} chunks, ~{estimated_tokens} tokens)"
    )

    if ctx:
        await ctx.info(message)

    result: dict[str, Any] = {
        "success": True,
        "message": message,
        "url": url,
        "content_type": content_type_name,
        "collection": target_collection,
        "chunks_created": chunks_created,
    }

    if response_format == "detailed":
        result.update({
            "estimated_tokens": estimated_tokens,
            "processing_time_ms": total_time_ms,
            "stages": stages,
            "content_length": len(content),
        })

    return result