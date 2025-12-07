# Advanced RAG Pipeline

A production-ready Retrieval-Augmented Generation (RAG) pipeline for OpenShift with LLM-driven chunking, hybrid search, and MCP server for AI agent integration.

## Features

- **Adaptive Chunking** – LLM-generated chunking plans tailored to document structure
- **Hybrid Search** – Dense vectors + BM25 with RRF fusion and reranking
- **Multiple Vector Stores** – Milvus (recommended), PGVector, or Meilisearch
- **MCP Server** – Agent integration for LibreChat, Claude Code, etc.
- **Self-Hosted Models** – Caikit embeddings/reranker, Ministral-8B/GPT-OSS LLM, Granite Vision

## Architecture

```
                                OpenShift Cluster
    +---------------------------------------------------------------------------+
    |                                                                           |
    |   +----------------+   +----------------+   +----------------------------+|
    |   | docling-serve  |   | granite-vision |   | caikit-embeddings          ||
    |   | (PDF->Markdown)|-->| (VLM for imgs) |   | (Embeddings + Reranker)    ||
    |   +-------+--------+   +----------------+   +----------------------------+|
    |           |                                                               |
    |           v                                                               |
    |   +----------------+   +----------------+   +----------------+            |
    |   |  plan-service  |-->|chunker-service |-->| embedding-svc  |            |
    |   | (LLM Planning) |   |   (Go binary)  |   |   (Batch embed)|            |
    |   +----------------+   +----------------+   +-------+--------+            |
    |                                                     |                     |
    |                                                     v                     |
    |   +----------------+   +----------------+   +----------------+            |
    |   | evaluator-svc  |   |  rerank-svc    |<--| vector-gateway |<--+        |
    |   | (QA scoring)   |   |  (Reranking)   |   | (Unified API)  |   |        |
    |   +----------------+   +----------------+   +-------+--------+   |        |
    |                                                     |            |        |
    |                                                     v            |        |
    |                                            +----------------+    |        |
    |                                            |     Milvus     |    |        |
    |                                            | (Vector Store) |    |        |
    |                                            +----------------+    |        |
    |                                                                  |        |
    |   +----------------+                                             |        |
    |   | retrieval-mcp  |---------------------------------------------+        |
    |   | (MCP Server)   |<-- AI Agents (LibreChat, Claude Code)                |
    |   +----------------+                                                      |
    |                                                                           |
    +---------------------------------------------------------------------------+
```

## Quick Deploy

```bash
oc login https://api.your-cluster.com:6443 --token=sha256~...
oc new-project advanced-rag              # Namespace must exist before deploy
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="your-llm-url"    # Optional: custom LLM endpoint
./deploy.sh
```

Deploys Milvus, all microservices, and MCP server to the `advanced-rag` namespace.

**Options:**
```bash
NAMESPACE=my-rag ./deploy.sh                       # Custom namespace (must exist)
SKIP_MILVUS=true ./deploy.sh                       # Use existing vector store
EMBEDDING_API_KEY=... LLM_API_KEY=... ./deploy.sh  # Separate keys per service
```

**No local tools?** Use the deployment toolbox:
```bash
# 1. Setup namespace and RBAC
export NAMESPACE=advanced-rag
oc new-project $NAMESPACE
oc apply -f toolbox/manifests/rbac.yaml -n $NAMESPACE

# 2. Run the toolbox with the service account
oc run toolbox --image=ghcr.io/kush-gupt/advanced-rag/toolbox:latest \
  --overrides='{"spec":{"serviceAccountName":"toolbox"}}' \
  -it --rm --restart=Never \
  --env="OPENAI_API_KEY=your-key" --env="NAMESPACE=$NAMESPACE" \
  -- deploy-helper deploy
```

## Project Structure

```
advanced-rag/
├── services/           # Microservices (chunker, embedding, rerank, vector-gateway, etc.)
├── retrieval-mcp/      # MCP server for AI agent integration
├── databases/          # Vector store configs (milvus, pgvector, meilisearch)
├── models/             # Self-hosted models (caikit, ministral-8b, gpt-oss, granite-vision)
├── docling-serve/      # PDF to Markdown conversion
├── toolbox/            # Deployment container with oc, helm, kustomize
├── pipelines/          # Kubeflow pipeline examples
└── deploy.sh           # One-shot deployment script
```

## Documentation

| Topic | Link |
|-------|------|
| **Getting Started** | [docs/OPENSHIFT_QUICKSTART.md](docs/OPENSHIFT_QUICKSTART.md) |
| **Deployment Toolbox** | [toolbox/README.md](toolbox/README.md) |
| **Microservices** | [services/README.md](services/README.md) |
| **MCP Server** | [retrieval-mcp/README.md](retrieval-mcp/README.md) |
| **Models** | [models/README.md](models/README.md) |
| **Vector Stores** | [databases/milvus/README.md](databases/milvus/README.md) |
| **Architecture** | [docs/architecture.md](docs/architecture.md) |

## Local Development

```bash
# Start local Milvus
cd databases/milvus/local && ./podman_milvus.sh start && cd ../../..

# Configure and run
export OPENAI_API_KEY="your-key" MILVUS_HOST=localhost MILVUS_PORT=19530
cd services/vector_gateway && PYTHONPATH=.. python app.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
