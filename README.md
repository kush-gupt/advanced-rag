# Advanced RAG Pipeline

A production-ready Retrieval-Augmented Generation (RAG) pipeline for OpenShift that uses LLM-driven chunking plans for optimal document segmentation. Features hybrid search (dense vectors + BM25), multiple vector store backends, and an MCP server for AI agent integration.

## Key Features

- **Adaptive Chunking**: LLM-generated chunking plans tailored to each document's structure
- **Hybrid Search**: Dense vectors + BM25 sparse search with RRF fusion and reranking
- **Multiple Vector Stores**: Milvus (recommended), PGVector, or Meilisearch
- **Microservices Architecture**: Independently deployable services for chunking, embedding, reranking, and retrieval
- **MCP Server**: FastMCP-based server for agent integration (LibreChat, Claude Code, etc.)
- **Self-Hosted Models**: Caikit embeddings/reranker, GPT-OSS LLM, and Granite Vision on OpenShift AI

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
    |                                            +----------------+   |        |
    |                                            |     Milvus     |   |        |
    |                                            | (Vector Store) |   |        |
    |                                            +----------------+   |        |
    |                                                                  |        |
    |   +----------------+                                             |        |
    |   | retrieval-mcp  |---------------------------------------------+        |
    |   | (MCP Server)   |<-- AI Agents (LibreChat, Claude Code)                |
    |   +----------------+                                                      |
    |                                                                           |
    +---------------------------------------------------------------------------+
```

## OpenShift Deployment Guide

This guide walks you through deploying the complete Advanced RAG pipeline to OpenShift. Follow the steps in order, as later components depend on earlier ones.

### Prerequisites

- OpenShift cluster with:
  - OpenShift AI (RHODS) for model serving
  - GPU nodes for VLM and LLM (optional but recommended)
  - At least 32GB RAM available for services
- `oc` CLI logged into your cluster
- SSH access to a Linux x86_64 build host (for Mac users building containers)
- API keys: OpenAI (or compatible), Cohere (for reranking) - *only if using cloud providers*

### Deployment Sequence

1. **Configuration** - Update `services/config/rag-config.yaml` for your cluster
2. **Namespaces & Secrets** - Create namespaces and configure API keys
3. **Models** - Deploy embedding, reranking, and LLM models
4. **Database** - Choose and deploy a vector store (Milvus recommended)
5. **Docling** - Deploy document conversion service
6. **Services** - Build and deploy the microservices
7. **MCP Server** - Deploy the retrieval MCP server for agent integration

---

### Step 1: Configure RAG Pipeline

Before deploying, update the configuration file to match your OpenShift cluster.

Edit `services/config/rag-config.yaml`:

1. **Update cluster URLs**: Replace the default cluster domain (`*.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com`) with your cluster's domain in the `base_url` fields for:
   - `caikit-granite` (embedding)
   - `caikit-minilm` (embedding, optional)
   - `caikit-reranker` (reranking)

2. **Choose providers**: The defaults use self-hosted Caikit models:
   - `embedding.active: caikit-granite` (768 dimensions)
   - `rerank.active: caikit-reranker`

   To use cloud APIs instead, change to `openai`, `cohere`, etc. and ensure the corresponding API keys are set.

3. **Environment variable overrides**: You can override providers at runtime:
   ```bash
   export RAG_EMBEDDING_PROVIDER=openai
   export RAG_RERANK_PROVIDER=cohere
   ```

See the config file comments for all available providers and their requirements.

---

### Step 2: Create Namespaces and Secrets

Create the namespaces and configure secrets needed by the services.

```bash
# Create primary namespace for RAG services
oc new-project advanced-rag

# Create secrets for API keys (used by plan-service, evaluator-service, embedding-service)
oc create secret generic api-keys \
  --from-literal=OPENAI_API_KEY="your-openai-key" \
  --from-literal=COHERE_API_KEY="your-cohere-key" \
  -n advanced-rag
```

If using self-hosted models on OpenShift AI, you may also need S3 credentials for model storage:

```bash
# Create secret for model storage (if using Noobaa/S3)
oc create secret generic model-storage-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="your-access-key" \
  --from-literal=AWS_SECRET_ACCESS_KEY="your-secret-key" \
  -n caikit-embeddings
```

---

### Step 3: Deploy Models

The RAG pipeline requires embedding models and optionally an LLM for plan generation and a VLM for image descriptions.

#### 3.1 Caikit Embeddings & Reranker

Deploy embedding and reranking models using OpenShift AI with the Caikit runtime:

```bash
# Create namespace
oc new-project caikit-embeddings

# Deploy Granite embedding model (768 dimensions)
oc apply -k models/caikit-embeddings/manifests/granite-embedding

# Deploy MiniLM embedding model (384 dimensions) - optional, lighter weight
oc apply -k models/caikit-embeddings/manifests/minilm-embedding

# Deploy MS-Marco reranker
oc apply -k models/caikit-embeddings/manifests/reranker

# Wait for pods
oc wait --for=condition=Ready pods -l app=granite-embedding -n caikit-embeddings --timeout=300s
```

See [models/caikit-embeddings/README.md](models/caikit-embeddings/README.md) for detailed instructions and API usage.

#### 3.2 GPT-OSS LLM (Optional)

For self-hosted LLM plan generation instead of OpenAI:

```bash
oc new-project gpt-oss
oc apply -k models/gpt-oss/manifests
oc wait --for=condition=Ready pods -l app=gpt-oss-20b-rhaiis -n gpt-oss --timeout=600s
```

See [models/gpt-oss/README.md](models/gpt-oss/README.md) for setup details.

#### 3.3 Granite Vision (Optional - Required for Image Descriptions)

If you want docling-serve to generate descriptions for images in PDFs, deploy this **before** deploying docling-serve with the GPU overlay:

```bash
oc new-project granite-vision
oc apply -k models/granite-vision/manifests/overlays/default
oc wait --for=condition=Ready pods -l app=granite-vision -n granite-vision --timeout=300s
```

See [models/granite-vision/README.md](models/granite-vision/README.md) for details.

---

### Step 4: Deploy Vector Database

Choose one of the supported vector stores. **Milvus is recommended** for its native hybrid search support.

#### Option A: Milvus (Recommended)

```bash
# Add Helm repo
helm repo add milvus https://zilliztech.github.io/milvus-helm/
helm repo update

# Install with OpenShift values
helm install milvus milvus/milvus \
  -f databases/milvus/openshift/values-openshift.yaml \
  -n milvus --create-namespace

# Wait for pods
oc wait --for=condition=Ready pods -l app.kubernetes.io/name=milvus -n milvus --timeout=300s
```

See [databases/milvus/README.md](databases/milvus/README.md) for configuration options.

#### Option B: PGVector

```bash
oc apply -k databases/pgvector/openshift/ -n advanced-rag
oc wait --for=condition=Ready pods -l app=pgvector -n advanced-rag --timeout=120s
```

See [databases/pgvector/README.md](databases/pgvector/README.md) for details.

#### Option C: Meilisearch

```bash
oc adm policy add-scc-to-user anyuid -z default -n meilisearch
oc apply -k databases/meilisearch/openshift/ -n meilisearch --create-namespace
```

See [databases/meilisearch/README.md](databases/meilisearch/README.md) for details.

---

### Step 5: Deploy Docling-Serve

Document conversion service for PDF to Markdown/JSON.

#### CPU Deployment (Dev/Test)

```bash
oc apply -k docling-serve/manifests/overlays/cpu
oc wait --for=condition=Available deployment/docling-serve -n docling-serve --timeout=120s
```

#### GPU Deployment with VLM (Production)

For automatic image descriptions, deploy the GPU overlay **after** deploying granite-vision (Step 3.3):

```bash
oc apply -k docling-serve/manifests/overlays/gpu
oc wait --for=condition=Available deployment/docling-serve -n docling-serve --timeout=180s
```

See [docling-serve/README.md](docling-serve/README.md) for configuration and usage.

---

### Step 6: Build and Deploy Microservices

The microservices handle chunking, embedding, reranking, evaluation, and vector operations.

#### 6.1 Build the Go Chunker Service

The chunker service is written in Go and needs to be compiled:

```bash
cd services/chunker_service
go build -o ../../bin/chunker ./cmd/chunker
cd ../..
```

#### 6.2 Build and Deploy All Services

Using the Makefile (recommended):

```bash
cd services

# Build all services remotely on ec2-dev (for Mac users)
make build-all

# Push images to OpenShift registry
make push-all

# Deploy all services
make deploy-all

# Verify health
make status
```

Or deploy individual services:

```bash
# Deploy vector-gateway first (other services may depend on it)
make deploy-gateway

# Then deploy remaining services
make deploy-chunker
make deploy-plan
make deploy-embedding
make deploy-rerank
make deploy-evaluator
```

#### 6.3 Verify Deployment

```bash
# Check all pods are running
oc get pods -n advanced-rag

# Test health endpoints
for svc in chunker-service plan-service embedding-service rerank-service evaluator-service vector-gateway; do
  echo -n "$svc: "
  curl -sk "https://${svc}-advanced-rag.apps.your-cluster.com/healthz"
  echo
done
```

See [services/README.md](services/README.md) for detailed API documentation and configuration.

---

### Step 7: Deploy Retrieval MCP Server

The MCP server exposes RAG capabilities to AI agents.

```bash
cd retrieval-mcp

# Deploy to advanced-rag namespace
make deploy PROJECT=advanced-rag

# Verify
oc get pods -n advanced-rag -l app=retrieval-mcp
```

#### Configure for LibreChat

Add to your LibreChat agent's MCP configuration:

```json
{
  "mcpServers": {
    "retrieval": {
      "url": "https://retrieval-mcp-advanced-rag.apps.your-cluster.com/mcp/"
    }
  }
}
```

See [retrieval-mcp/README.md](retrieval-mcp/README.md) for all available tools and integration examples.

---

### Step 8: Test the Pipeline

Use the example Kubeflow pipeline to verify everything works:

```bash
# Compile the example pipeline
pip install kfp
python pipelines/example/pipeline.py

# Upload pipelines/example/ingest_pipeline.yaml to Kubeflow
# Run with test_data/drylab.pdf (upload to accessible URL first)
```

Or test manually with curl:

```bash
# Set your cluster's route URLs
DOCLING_URL="https://docling-serve-docling-serve.apps.your-cluster.com"
GATEWAY_URL="https://vector-gateway-advanced-rag.apps.your-cluster.com"

# Convert a document
curl -X POST "$DOCLING_URL/v1/convert/file/async" \
  -F "files=@test_data/drylab.pdf" \
  -F "to_formats=md"

# Search (after ingestion)
curl -X POST "$GATEWAY_URL/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "collection": "my_collection", "top_k": 5}'
```

See [pipelines/example/README.md](pipelines/example/README.md) for the full example pipeline.

---

## Project Structure

```
advanced-rag/
├── services/                     # Deployable microservices
│   ├── chunker_service/          # Go: sliding-window text chunking
│   ├── plan_service/             # Python: LLM chunking plan generator
│   ├── embedding_service/        # Python: batch embeddings
│   ├── rerank_service/           # Python: result reranking
│   ├── evaluator_service/        # Python: QA evaluation
│   ├── vector_gateway/           # Python: unified vector store API
│   ├── rag_core/                 # Shared Python library
│   └── Makefile                  # Build/deploy automation
├── retrieval-mcp/                # FastMCP server for RAG retrieval
├── databases/                    # Vector store configurations
│   ├── milvus/                   # Milvus (recommended)
│   ├── pgvector/                 # PostgreSQL + pgvector
│   └── meilisearch/              # Meilisearch
├── models/                       # Self-hosted model deployments
│   ├── caikit-embeddings/        # Embedding + reranker models
│   ├── gpt-oss/                  # GPT-OSS LLM
│   └── granite-vision/           # Vision language model
├── docling-serve/                # Document conversion service
├── pipelines/                    # Kubeflow pipelines
│   └── example/                  # Example ingest pipeline
├── test_data/                    # Sample files for testing
├── docs/                         # Additional documentation
└── bin/                          # Compiled binaries (gitignored)
```

## Documentation

| Document | Description |
|----------|-------------|
| [services/README.md](services/README.md) | Microservices API reference and deployment |
| [retrieval-mcp/README.md](retrieval-mcp/README.md) | MCP server tools and agent integration |
| [models/README.md](models/README.md) | Self-hosted model deployment |
| [databases/milvus/README.md](databases/milvus/README.md) | Milvus setup and usage |
| [docling-serve/README.md](docling-serve/README.md) | Document conversion service |
| [pipelines/README.md](pipelines/README.md) | Kubeflow pipeline examples |
| [docs/architecture.md](docs/architecture.md) | System design and data flow |
| [docs/vector-stores.md](docs/vector-stores.md) | Vector store comparison |

## Local Development

For local development without OpenShift:

```bash
# Clone and set up environment
git clone <repository-url>
cd advanced-rag
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start local vector store
cd databases/milvus/local && ./podman_milvus.sh start && cd ../../..

# Build Go chunker
cd services/chunker_service && go build -o ../../bin/chunker ./cmd/chunker && cd ../..

# Configure
export OPENAI_API_KEY="your-api-key"
export MILVUS_HOST=localhost
export MILVUS_PORT=19530

# Run services locally
cd services/vector_gateway && PYTHONPATH=.. python app.py &
cd services/embedding_service && PYTHONPATH=.. python app.py &
# ... start other services as needed
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
