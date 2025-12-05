# OpenShift Web Terminal Quickstart

Deploy the complete Advanced RAG pipeline from an OpenShift web terminal using pre-built container images.

## One-Command Deploy

```bash
git clone https://github.com/kush-gupt/advanced-rag.git
cd advanced-rag
export OPENAI_API_KEY="your-openai-api-key"
./deploy.sh
```

That's it! The script will deploy Milvus, all services, and the MCP server.

## Prerequisites

- OpenShift cluster access (logged in via `oc login`)
- Helm 3.x (`helm version`)
- API key: OpenAI or compatible provider

## Configuration Options

Set these environment variables before running `deploy.sh`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NAMESPACE` | `advanced-rag` | Target namespace |
| `OPENAI_API_KEY` | (required) | API key for LLM services |
| `COHERE_API_KEY` | (uses OPENAI_API_KEY) | API key for Cohere reranking |
| `SKIP_MILVUS` | `false` | Skip Milvus deployment |
| `SKIP_SERVICES` | `false` | Skip service deployment |
| `SKIP_MCP` | `false` | Skip MCP server deployment |

### Custom Namespace

```bash
export OPENAI_API_KEY="your-key"
export NAMESPACE="my-rag-project"
./deploy.sh
```

## Manual Deployment

If you prefer step-by-step deployment:

### 1. Clone and Setup

```bash
git clone https://github.com/kush-gupt/advanced-rag.git
cd advanced-rag

export NAMESPACE=advanced-rag
export OPENAI_API_KEY="your-openai-api-key"
```

### 2. Create Namespace and Secrets

```bash
oc new-project $NAMESPACE 2>/dev/null || oc project $NAMESPACE

oc create secret generic embedding-service-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -

oc create secret generic plan-service-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -

oc create secret generic evaluator-service-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -

oc create secret generic vector-gateway-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -

oc create secret generic rerank-service-secrets \
  --from-literal=COHERE_API_KEY="$OPENAI_API_KEY" \
  --from-literal=RERANK_API_KEY="$OPENAI_API_KEY" -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -
```

### 3. Deploy Milvus

```bash
helm repo add zilliztech https://zilliztech.github.io/milvus-helm/
helm repo update

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
cd services
make deploy-all NAMESPACE=$NAMESPACE
cd ..
```

### 5. Deploy MCP Server (Optional)

```bash
kustomize build retrieval-mcp/manifests/overlays/ghcr | oc apply -n $NAMESPACE -f -
```

### 6. Verify

```bash
oc get pods -n $NAMESPACE
oc get routes -n $NAMESPACE
```

## Service URLs

After deployment, services are available at:

| Service | URL |
|---------|-----|
| Vector Gateway | `https://vector-gateway-$NAMESPACE.$CLUSTER_DOMAIN` |
| Embedding Service | `https://embedding-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Rerank Service | `https://rerank-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Plan Service | `https://plan-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Evaluator Service | `https://evaluator-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Chunker Service | `https://chunker-service-$NAMESPACE.$CLUSTER_DOMAIN` |
| Retrieval MCP | `https://retrieval-mcp-$NAMESPACE.$CLUSTER_DOMAIN/mcp/` |

Get your cluster domain with:
```bash
oc get ingresses.config/cluster -o jsonpath='{.spec.domain}'
```

## Test the Pipeline

```bash
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
GATEWAY_URL="https://vector-gateway-${NAMESPACE}.${CLUSTER_DOMAIN}"

# Ingest a document
curl -X POST "$GATEWAY_URL/upsert" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [{"text": "RAG pipelines combine retrieval and generation.", "metadata": {"source": "test"}}],
    "collection": "test"
  }'

# Search
curl -X POST "$GATEWAY_URL/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "How do RAG pipelines work?", "collection": "test", "top_k": 5}'
```

## Troubleshooting

### Check pod status
```bash
oc get pods -n $NAMESPACE
oc describe pod <pod-name> -n $NAMESPACE
```

### View logs
```bash
oc logs deployment/vector-gateway -n $NAMESPACE
oc logs deployment/milvus-standalone -n $NAMESPACE
```

### Restart a service
```bash
oc rollout restart deployment/vector-gateway -n $NAMESPACE
```

## Cleanup

```bash
# Delete services
oc delete all -l app.kubernetes.io/part-of=advanced-rag -n $NAMESPACE

# Delete Milvus
helm uninstall milvus -n $NAMESPACE

# Delete namespace
oc delete project $NAMESPACE
```

## Container Images

All images are pre-built and available from GitHub Container Registry:

| Service | Image |
|---------|-------|
| chunker-service | `ghcr.io/kush-gupt/advanced-rag/chunker-service:latest` |
| embedding-service | `ghcr.io/kush-gupt/advanced-rag/embedding-service:latest` |
| evaluator-service | `ghcr.io/kush-gupt/advanced-rag/evaluator-service:latest` |
| plan-service | `ghcr.io/kush-gupt/advanced-rag/plan-service:latest` |
| rerank-service | `ghcr.io/kush-gupt/advanced-rag/rerank-service:latest` |
| vector-gateway | `ghcr.io/kush-gupt/advanced-rag/vector-gateway:latest` |
| retrieval-mcp | `ghcr.io/kush-gupt/advanced-rag/retrieval-mcp:latest` |
