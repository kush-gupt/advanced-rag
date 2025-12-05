# OpenShift Quickstart

Deploy the complete Advanced RAG pipeline to OpenShift using pre-built container images.

## Option 1: Toolbox Container (Recommended)

Run the deployment toolbox directly in your cluster—no local tools required:

```bash
oc run toolbox \
  --image=ghcr.io/kush-gupt/advanced-rag/toolbox:latest \
  -it --rm --restart=Never -- bash

# Inside the toolbox:
git clone https://github.com/kush-gupt/advanced-rag.git
cd advanced-rag
export OPENAI_API_KEY="your-key"
./deploy.sh
```

## Option 2: Web Terminal

From an OpenShift web terminal (requires git, helm, kustomize installed):

```bash
git clone https://github.com/kush-gupt/advanced-rag.git
cd advanced-rag
export OPENAI_API_KEY="your-key"
./deploy.sh
```

## Prerequisites

- OpenShift cluster access (`oc login`)
- API key: OpenAI or compatible provider
- For Option 2: helm 3.x and kustomize

## Configuration

### Basic

| Variable | Default | Description |
|----------|---------|-------------|
| `NAMESPACE` | `advanced-rag` | Target namespace |
| `OPENAI_API_KEY` | (required) | Default API key for all services |
| `OPENAI_BASE_URL` | OpenAI | Default base URL for all services |
| `SKIP_MILVUS` | `false` | Skip Milvus deployment |
| `SKIP_SERVICES` | `false` | Skip service deployment |
| `SKIP_MCP` | `false` | Skip MCP server deployment |

### Model-Specific Endpoints

Different services use different model types. Override these for OpenShift AI or self-hosted models:

| Variable | Falls back to | Used by | Model type |
|----------|---------------|---------|------------|
| `EMBEDDING_API_KEY` | `OPENAI_API_KEY` | embedding-service, vector-gateway | Embedding |
| `EMBEDDING_BASE_URL` | `OPENAI_BASE_URL` | embedding-service, vector-gateway | Embedding |
| `LLM_API_KEY` | `OPENAI_API_KEY` | plan-service, evaluator-service | LLM/Chat |
| `LLM_BASE_URL` | `OPENAI_BASE_URL` | plan-service, evaluator-service | LLM/Chat |
| `RERANK_API_KEY` | `COHERE_API_KEY` → `OPENAI_API_KEY` | rerank-service | Reranker |
| `RERANK_BASE_URL` | `OPENAI_BASE_URL` | rerank-service | Reranker |

### Examples

**Single provider (OpenAI for everything):**
```bash
export OPENAI_API_KEY="sk-..."
./deploy.sh
```

**OpenShift AI with separate model endpoints:**
```bash
export OPENAI_API_KEY="not-used"  # fallback, not actually called

# Embedding model on OpenShift AI
export EMBEDDING_API_KEY="token-for-embeddings"
export EMBEDDING_BASE_URL="https://embed-model.apps.cluster.example.com/v1"

# LLM on OpenShift AI
export LLM_API_KEY="token-for-llm"
export LLM_BASE_URL="https://llm-model.apps.cluster.example.com/v1"

# Reranker on OpenShift AI
export RERANK_API_KEY="token-for-rerank"
export RERANK_BASE_URL="https://rerank-model.apps.cluster.example.com/v1"

./deploy.sh
```

**Hybrid: OpenAI LLM + self-hosted embeddings:**
```bash
export OPENAI_API_KEY="sk-..."                            # For LLM
export EMBEDDING_API_KEY="local-token"
export EMBEDDING_BASE_URL="http://embed-svc.ns.svc:8000/v1"
./deploy.sh
```

## Manual Deployment

### 1. Set Up

```bash
git clone https://github.com/kush-gupt/advanced-rag.git && cd advanced-rag
export NAMESPACE=advanced-rag OPENAI_API_KEY="your-key"
```

### 2. Create Namespace and Secrets

```bash
oc new-project $NAMESPACE 2>/dev/null || oc project $NAMESPACE

for svc in embedding-service plan-service evaluator-service vector-gateway; do
  oc create secret generic ${svc}-secrets \
    --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -
done

oc create secret generic rerank-service-secrets \
  --from-literal=COHERE_API_KEY="$OPENAI_API_KEY" \
  --from-literal=RERANK_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -
```

### 3. Deploy Milvus

```bash
helm repo add zilliztech https://zilliztech.github.io/milvus-helm/ && helm repo update

helm install milvus zilliztech/milvus \
  --set cluster.enabled=false \
  --set etcd.podSecurityContext.enabled=false \
  --set etcd.containerSecurityContext.enabled=false \
  --set etcd.volumePermissions.enabled=false \
  --set minio.podSecurityContext.enabled=false \
  --set minio.containerSecurityContext.enabled=false \
  --set standalone.messageQueue=rocksmq \
  -n $NAMESPACE

oc wait --for=condition=Ready pods -l app.kubernetes.io/name=milvus -n $NAMESPACE --timeout=300s
```

### 4. Deploy Services

```bash
cd services && make deploy-all NAMESPACE=$NAMESPACE && cd ..
```

### 5. Deploy MCP Server

```bash
kustomize build retrieval-mcp/manifests/overlays/ghcr | oc apply -n $NAMESPACE -f -
```

### 6. Verify

```bash
oc get pods,routes -n $NAMESPACE
```

## Service URLs

```bash
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
echo "Vector Gateway: https://vector-gateway-${NAMESPACE}.${CLUSTER_DOMAIN}"
```

| Service | Path |
|---------|------|
| Vector Gateway | `https://vector-gateway-$NAMESPACE.$CLUSTER_DOMAIN` |
| Embedding Service | `https://embedding-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Rerank Service | `https://rerank-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Plan Service | `https://plan-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Evaluator Service | `https://evaluator-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Chunker Service | `https://chunker-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Retrieval MCP | `https://retrieval-mcp-$NAMESPACE.$CLUSTER_DOMAIN/mcp/` |

## Test

```bash
GATEWAY_URL="https://vector-gateway-${NAMESPACE}.${CLUSTER_DOMAIN}"

curl -X POST "$GATEWAY_URL/upsert" -H "Content-Type: application/json" \
  -d '{"documents": [{"text": "RAG combines retrieval and generation.", "metadata": {"source": "test"}}], "collection": "test"}'

curl -X POST "$GATEWAY_URL/search" -H "Content-Type: application/json" \
  -d '{"query": "How do RAG pipelines work?", "collection": "test", "top_k": 5}'
```

## Troubleshooting

```bash
oc get pods -n $NAMESPACE
oc logs deployment/vector-gateway -n $NAMESPACE
oc rollout restart deployment/vector-gateway -n $NAMESPACE
```

## Cleanup

```bash
oc delete all -l app.kubernetes.io/part-of=advanced-rag -n $NAMESPACE
helm uninstall milvus -n $NAMESPACE
oc delete project $NAMESPACE
```

## Container Images

| Service | Image |
|---------|-------|
| toolbox | `ghcr.io/kush-gupt/advanced-rag/toolbox:latest` |
| chunker-service | `ghcr.io/kush-gupt/advanced-rag/chunker-service:latest` |
| embedding-service | `ghcr.io/kush-gupt/advanced-rag/embedding-service:latest` |
| evaluator-service | `ghcr.io/kush-gupt/advanced-rag/evaluator-service:latest` |
| plan-service | `ghcr.io/kush-gupt/advanced-rag/plan-service:latest` |
| rerank-service | `ghcr.io/kush-gupt/advanced-rag/rerank-service:latest` |
| vector-gateway | `ghcr.io/kush-gupt/advanced-rag/vector-gateway:latest` |
| retrieval-mcp | `ghcr.io/kush-gupt/advanced-rag/retrieval-mcp:latest` |
