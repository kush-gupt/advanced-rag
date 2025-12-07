# Ingestion MCP - Tools Plan

> Optimized based on [Anthropic's "Writing Tools for Agents"](https://www.anthropic.com/engineering/writing-tools-for-agents)

## Overview

The ingestion-mcp provides document ingestion capabilities for the RAG pipeline. It orchestrates the flow from file upload through document parsing, chunking, and storage in the vector database.

## Design Principles Applied

1. **Purposeful tools** - Each tool targets a specific high-impact workflow
2. **Consolidated operations** - Combined list + stats into single `get_collections` tool
3. **High-signal responses** - Return actionable info, not low-level IDs
4. **Instructive errors** - Guide agents toward correct behavior
5. **Response format control** - Let agents choose verbosity level

## Architecture

```
┌─────────────────┐
│  ingestion-mcp  │
│                 │
│  ┌───────────┐  │     ┌──────────────────┐
│  │ ingest_*  │──┼────▶│  Docling Service │ (document parsing)
│  │  tools    │  │     └──────────────────┘
│  └───────────┘  │              │
│        │        │              ▼
│        │        │     ┌──────────────────┐
│        │        ├────▶│ chunker-service  │ (text chunking)
│        │        │     └──────────────────┘
│        │        │              │
│        │        │              ▼
│        │        │     ┌──────────────────┐
│        └────────┼────▶│  vector-gateway  │ (embed + store)
│                 │     └──────────────────┘
└─────────────────┘              │
                                 ▼
                        ┌──────────────────┐
                        │     Milvus       │
                        └──────────────────┘
```

## Dependencies (External Services)

| Service | URL (OpenShift) | Purpose |
|---------|-----------------|---------|
| Docling | `DOCLING_SERVICE_URL` | Document parsing (PDF, DOCX, etc.) |
| Chunker | `CHUNKER_SERVICE_URL` | Text chunking with sliding window |
| Vector Gateway | `VECTOR_GATEWAY_URL` | Embedding + Milvus storage |

---

## Tools

### 1. `ingest_document`

**Purpose**: Main tool for ingesting a document file into the vector database.

**Input Schema**:
```json
{
  "file_path": "string (required) - Path to the file to ingest",
  "collection": "string (optional) - Target Milvus collection",
  "source": "string (optional) - Source identifier for tracking",
  "tags": "array of strings (optional) - Tags for filtering",
  "chunking": "string (optional) - 'default' | 'dense' | 'sparse'",
  "response_format": "string (optional) - 'concise' | 'detailed'"
}
```

**Chunking Presets** (simplifies config for agents):
| Preset | Window | Overlap | Use Case |
|--------|--------|---------|----------|
| `default` | 200 | 40 | General documents |
| `dense` | 100 | 30 | High-precision retrieval |
| `sparse` | 400 | 60 | Long-form content |

**Output Schema (concise)**:
```json
{
  "success": true,
  "message": "Successfully ingested report.pdf into legal_docs (42 chunks, ~8500 tokens)",
  "file_name": "report.pdf",
  "collection": "legal_docs",
  "chunks_created": 42
}
```

**Output Schema (detailed)**:
```json
{
  "success": true,
  "message": "Successfully ingested report.pdf into legal_docs (42 chunks, ~8500 tokens)",
  "file_name": "report.pdf",
  "collection": "legal_docs",
  "chunks_created": 42,
  "estimated_tokens": 8500,
  "processing_time_ms": 3200,
  "stages": {
    "parsing_ms": 1200,
    "chunking_ms": 400,
    "embedding_ms": 1600
  },
  "warnings": []
}
```

**Error Examples** (instructive, not opaque):
```json
{
  "success": false,
  "error": "File not found: /path/to/doc.pdf. Verify the file exists and the path is absolute.",
  "suggestion": "Use ingest_from_url if the document is hosted remotely."
}
```

```json
{
  "success": false,
  "error": "Unsupported file type: .xyz. Supported types: PDF, DOCX, TXT, MD, HTML.",
  "suggestion": "Convert the file to a supported format or use ingest_text with pre-extracted content."
}
```

```json
{
  "success": false,
  "error": "Document parsing failed: PDF is password-protected.",
  "suggestion": "Remove password protection or provide the decrypted content via ingest_text."
}
```

**Flow**:
1. Validate file exists and is supported type
2. Call Docling service to extract text
3. Call chunker-service with selected preset
4. Call vector-gateway `/upsert` to embed and store chunks
5. Return summary with actionable message

---

### 2. `ingest_text`

**Purpose**: Ingest raw text directly (skip document parsing). Use when text is already extracted.

**Input Schema**:
```json
{
  "text": "string (required) - The text to ingest",
  "collection": "string (optional) - Target collection",
  "name": "string (optional) - Identifier for this content",
  "source": "string (optional) - Origin of the text",
  "tags": "array (optional)",
  "chunking": "string (optional) - 'default' | 'dense' | 'sparse'",
  "response_format": "string (optional) - 'concise' | 'detailed'"
}
```

**Output Schema (concise)**:
```json
{
  "success": true,
  "message": "Ingested text 'meeting-notes' into rag_gateway (5 chunks)",
  "name": "meeting-notes",
  "collection": "rag_gateway",
  "chunks_created": 5
}
```

**Error Example**:
```json
{
  "success": false,
  "error": "Text too short (23 characters). Minimum is 50 characters for meaningful chunking.",
  "suggestion": "Provide more content or combine with other text before ingesting."
}
```

**Flow**:
1. Validate text length
2. Call chunker-service
3. Call vector-gateway `/upsert`
4. Return summary

---

### 3. `ingest_from_url`

**Purpose**: Fetch and ingest content from a URL. Useful for PDFs and documents hosted remotely that agents cannot fetch directly.

**Input Schema**:
```json
{
  "url": "string (required) - URL to fetch and ingest",
  "collection": "string (optional)",
  "source": "string (optional, defaults to URL domain)",
  "tags": "array (optional)",
  "chunking": "string (optional) - 'default' | 'dense' | 'sparse'",
  "response_format": "string (optional) - 'concise' | 'detailed'"
}
```

**Output Schema (concise)**:
```json
{
  "success": true,
  "message": "Ingested https://example.com/report.pdf into rag_gateway (25 chunks)",
  "url": "https://example.com/report.pdf",
  "content_type": "PDF",
  "collection": "rag_gateway",
  "chunks_created": 25
}
```

**Error Examples**:
```json
{
  "success": false,
  "error": "URL fetch failed: 404 Not Found",
  "suggestion": "Verify the URL is correct and publicly accessible."
}
```

```json
{
  "success": false,
  "error": "URL fetch failed: SSL certificate verification failed",
  "suggestion": "The server's SSL certificate is invalid. Contact the site administrator or use a different source."
}
```

**Flow**:
1. Fetch URL content
2. Detect content type from headers/content
3. Route: PDF/DOCX → Docling, HTML → text extraction, TXT/MD → direct
4. Chunk and store
5. Return summary

---

### 4. `get_collections`

**Purpose**: Discover available collections and optionally get stats for a specific collection. Consolidates list + stats into one tool.

**Input Schema**:
```json
{
  "collection": "string (optional) - If provided, return stats for this collection"
}
```

**Output Schema (no collection specified - list mode)**:
```json
{
  "collections": [
    {"name": "rag_gateway", "document_count": 1542},
    {"name": "legal_docs", "document_count": 328},
    {"name": "support_tickets", "document_count": 5210}
  ],
  "total_collections": 3,
  "message": "Found 3 collections with 7080 total documents"
}
```

**Output Schema (collection specified - stats mode)**:
```json
{
  "name": "legal_docs",
  "document_count": 328,
  "files": ["contract_v1.pdf", "terms_of_service.docx", "privacy_policy.md"],
  "file_count": 3,
  "message": "Collection 'legal_docs' contains 328 chunks from 3 files"
}
```

**Error Example**:
```json
{
  "success": false,
  "error": "Collection 'unknown_collection' not found.",
  "suggestion": "Use get_collections without parameters to see available collections.",
  "available_collections": ["rag_gateway", "legal_docs", "support_tickets"]
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DOCLING_SERVICE_URL` | Yes | - | URL of Docling service |
| `CHUNKER_SERVICE_URL` | Yes | - | URL of chunker service |
| `VECTOR_GATEWAY_URL` | Yes | - | URL of vector gateway |
| `AUTH_TOKEN` | No | - | Optional auth token for services |
| `DEFAULT_COLLECTION` | No | `rag_gateway` | Default Milvus collection |

---

## Open Questions for Discussion

1. **File upload mechanism**: How does the agent provide files?
   - Option A: File path (file must be accessible to MCP server)
   - Option B: Base64-encoded content in request
   - Option C: URL only (remove `ingest_document`, keep only `ingest_from_url`)

2. **Docling deployment**: Is there an existing Docling service?
   - If not, deploy one or bundle in ingestion-mcp container

3. **Async processing**: Start sync, add async job support later if needed?

4. **Batch ingestion**: Add `ingest_batch` tool in Phase 2?

---

## Implementation Priority

### Phase 1 (MVP)
- `ingest_document` - Core file ingestion
- `ingest_text` - Raw text ingestion
- `get_collections` - Discovery (consolidated)

### Phase 2 (Enhancement)
- `ingest_from_url` - Remote content
- Batch ingestion support
- Duplicate detection (hash-based)

### Phase 3 (Future)
- Async processing with job status
- Progress callbacks for large documents
- Collection management (create/delete)
