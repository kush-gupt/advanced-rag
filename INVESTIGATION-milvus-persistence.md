# Investigation: Milvus Document Persistence Issue

## Problem Statement

Documents are successfully ingested via the ingestion-mcp server (we receive success responses), but document counts don't increase when querying collection stats.

## Observations

1. **Successful upsert responses**: The vector-gateway returns success for document upserts
2. **Static row counts**: After multiple ingestions, `rag_gateway` collection shows `row_count: 1`
3. **Other collections work**: `servicenow_kb` shows 1,350 documents, indicating persistence works in some cases

## Affected Services

- `vector-gateway-advanced-rag.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com`
- Milvus (backend vector database)
- `retrieval-mcp` (may use same infrastructure)

## Areas to Investigate

### 1. Vector Gateway

- [ ] Check `/documents/upsert` endpoint implementation
- [ ] Verify Milvus client configuration
- [ ] Check if there's a flush/commit step being skipped
- [ ] Review error handling - are failures silently swallowed?

### 2. Milvus Configuration

- [ ] Check if auto-flush is enabled
- [ ] Verify collection consistency level settings
- [ ] Check if there are segment/index issues
- [ ] Review Milvus logs for errors

### 3. Retrieval MCP

- [ ] Test retrieval of recently ingested documents
- [ ] Compare retrieval-mcp implementation with vector-gateway

## Test Cases

```bash
# Test 1: Direct vector-gateway upsert
curl -X POST "https://vector-gateway-advanced-rag.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com/documents/upsert" \
  -H "Content-Type: application/json" \
  -d '{...}'

# Test 2: Check stats before and after
curl "https://vector-gateway-advanced-rag.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com/collections/rag_gateway/stats"

# Test 3: Try to retrieve recently ingested content
# (via retrieval-mcp)
```

## Findings

### Root Cause Identified

The issue is **NOT a persistence problem** - documents ARE being stored correctly. The issue is that **Milvus data isn't immediately visible** after insert.

**Milvus Growing Segment Behavior:**
1. Data is first inserted into a "growing segment"
2. Growing segments are not immediately visible in `get_collection_stats()` row counts
3. Data becomes visible when:
   - Auto-flush triggers (time/size threshold)
   - The segment is manually flushed
   - A query loads the collection

**Evidence:**
- Initial stats showed `row_count: 1`
- After waiting ~10 minutes, stats showed `row_count: 5`
- All ingested documents were actually persisted, just not visible in stats

### File Modified

`services/vector_gateway/lib/milvus_io.py` line 143-145:
```python
client.insert(collection_name=collection_name, data=rows)
# Flush to ensure data is immediately visible in stats and queries
client.flush(collection_name=collection_name)
```

## Resolution

Added explicit `flush()` call after `insert()` in `insert_chunks()` function to ensure data is immediately visible in stats and queries.

**Trade-offs:**
- Pro: Data immediately visible after upsert
- Con: Slightly slower upserts due to flush overhead
- For RAG ingestion use case, consistency is more important than raw speed
