#!/bin/bash
# Advanced RAG - OpenShift Deployment Script
#
# Usage:
#   export OPENAI_API_KEY="your-key"
#   ./deploy.sh
#
# Environment Variables:
#   NAMESPACE            Target namespace (default: advanced-rag, must exist)
#
#   # Universal fallback
#   OPENAI_API_KEY       Required: default API key for all services
#   OPENAI_BASE_URL      Optional: default base URL for all services
#
#   # Embedding-specific (embedding-service, vector-gateway)
#   EMBEDDING_API_KEY    API key for embedding model (falls back to OPENAI_API_KEY)
#   EMBEDDING_BASE_URL   Base URL for embedding model (falls back to OPENAI_BASE_URL)
#
#   # LLM-specific (plan-service)
#   LLM_API_KEY          API key for LLM (falls back to OPENAI_API_KEY)
#   LLM_BASE_URL         Base URL for LLM (falls back to OPENAI_BASE_URL)
#
#   # Rerank-specific (rerank-service)
#   RERANK_API_KEY       API key for reranker (falls back to COHERE_API_KEY, then OPENAI_API_KEY)
#   RERANK_BASE_URL      Base URL for reranker (falls back to OPENAI_BASE_URL)
#   COHERE_API_KEY       Legacy: Cohere API key
#
#   # Skip flags
#   SKIP_MILVUS          Skip Milvus deployment
#   SKIP_SERVICES        Skip service deployment
#   SKIP_MCP             Skip MCP server deployment

set -e

RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' NC='\033[0m'
log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

NAMESPACE="${NAMESPACE:-advanced-rag}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_prerequisites() {
    log "Checking prerequisites..."
    command -v oc >/dev/null 2>&1 || error "oc CLI not found"
    command -v kustomize >/dev/null 2>&1 || error "kustomize not found"
    [[ "$SKIP_MILVUS" == "true" ]] || command -v helm >/dev/null 2>&1 || error "helm not found"
    oc whoami >/dev/null 2>&1 || error "Not logged into OpenShift"
    [[ -n "$OPENAI_API_KEY" ]] || error "OPENAI_API_KEY is required"
    log "Prerequisites OK"
}

setup_namespace() {
    log "Using namespace: $NAMESPACE"
    
    # If running inside a pod, we're already in the namespace - just verify access
    if [[ -f /var/run/secrets/kubernetes.io/serviceaccount/namespace ]]; then
        local POD_NS=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)
        if [[ "$POD_NS" != "$NAMESPACE" ]]; then
            warn "Running in namespace '$POD_NS' but NAMESPACE='$NAMESPACE'. Using '$POD_NS'."
            NAMESPACE="$POD_NS"
        fi
        # Verify we have access by listing pods (uses our RBAC permissions)
        oc get pods -n "$NAMESPACE" --no-headers >/dev/null 2>&1 || error "Cannot access namespace '$NAMESPACE'. Check RBAC permissions."
    else
        # Running locally - check namespace exists and switch to it
        oc get namespace "$NAMESPACE" >/dev/null 2>&1 || error "Namespace '$NAMESPACE' does not exist. Create it first."
        oc project "$NAMESPACE"
    fi
}

create_secrets() {
    log "Creating secrets..."
    
    # Resolve API keys with fallback chain
    local EMBED_KEY="${EMBEDDING_API_KEY:-$OPENAI_API_KEY}"
    local EMBED_URL="${EMBEDDING_BASE_URL:-$OPENAI_BASE_URL}"
    local LLM_KEY="${LLM_API_KEY:-$OPENAI_API_KEY}"
    local LLM_URL="${LLM_BASE_URL:-$OPENAI_BASE_URL}"
    local RERANK_KEY="${RERANK_API_KEY:-${COHERE_API_KEY:-$OPENAI_API_KEY}}"
    local RERANK_URL="${RERANK_BASE_URL:-$OPENAI_BASE_URL}"
    
    # Embedding service (uses embedding model)
    oc create secret generic embedding-service-secrets \
        --from-literal=OPENAI_API_KEY="$EMBED_KEY" \
        --from-literal=EMBEDDING_API_KEY="$EMBED_KEY" \
        ${EMBED_URL:+--from-literal=OPENAI_BASE_URL="$EMBED_URL"} \
        ${EMBED_URL:+--from-literal=EMBEDDING_BASE_URL="$EMBED_URL"} \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Plan service (uses LLM)
    oc create secret generic plan-service-secrets \
        --from-literal=OPENAI_API_KEY="$LLM_KEY" \
        --from-literal=OPENAI_PLAN_API_KEY="$LLM_KEY" \
        ${LLM_URL:+--from-literal=OPENAI_BASE_URL="$LLM_URL"} \
        ${LLM_URL:+--from-literal=OPENAI_PLAN_BASE_URL="$LLM_URL"} \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Evaluator service (uses LLM)
    oc create secret generic evaluator-service-secrets \
        --from-literal=OPENAI_API_KEY="$LLM_KEY" \
        ${LLM_URL:+--from-literal=OPENAI_BASE_URL="$LLM_URL"} \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Vector gateway (uses embedding model)
    oc create secret generic vector-gateway-secrets \
        --from-literal=OPENAI_API_KEY="$EMBED_KEY" \
        --from-literal=EMBEDDING_API_KEY="$EMBED_KEY" \
        ${EMBED_URL:+--from-literal=OPENAI_BASE_URL="$EMBED_URL"} \
        ${EMBED_URL:+--from-literal=EMBEDDING_BASE_URL="$EMBED_URL"} \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Rerank service
    oc create secret generic rerank-service-secrets \
        --from-literal=RERANK_API_KEY="$RERANK_KEY" \
        --from-literal=COHERE_API_KEY="$RERANK_KEY" \
        ${RERANK_URL:+--from-literal=OPENAI_BASE_URL="$RERANK_URL"} \
        ${RERANK_URL:+--from-literal=RERANK_BASE_URL="$RERANK_URL"} \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    log "Secrets created"
}

deploy_milvus() {
    [[ "$SKIP_MILVUS" == "true" ]] && { warn "Skipping Milvus (SKIP_MILVUS=true)"; return; }
    
    log "Deploying Milvus..."
    helm repo add zilliztech https://zilliztech.github.io/milvus-helm/ 2>/dev/null || true
    helm repo update
    
    local HELM_ARGS=(
        --set cluster.enabled=false
        --set etcd.podSecurityContext.enabled=false
        --set etcd.containerSecurityContext.enabled=false
        --set etcd.volumePermissions.enabled=false
        --set minio.podSecurityContext.enabled=false
        --set minio.containerSecurityContext.enabled=false
        --set standalone.messageQueue=rocksmq
    )
    
    if helm status milvus -n "$NAMESPACE" >/dev/null 2>&1; then
        helm upgrade milvus zilliztech/milvus "${HELM_ARGS[@]}" -n "$NAMESPACE"
    else
        helm install milvus zilliztech/milvus "${HELM_ARGS[@]}" -n "$NAMESPACE"
    fi
    
    log "Waiting for Milvus..."
    oc wait --for=condition=Ready pods -l app.kubernetes.io/name=milvus -n "$NAMESPACE" --timeout=300s || warn "Milvus not ready yet"
}

deploy_services() {
    [[ "$SKIP_SERVICES" == "true" ]] && { warn "Skipping services (SKIP_SERVICES=true)"; return; }
    
    log "Deploying services..."
    for svc in chunker_service embedding_service evaluator_service plan_service rerank_service vector_gateway; do
        log "  $svc..."
        kustomize build "$SCRIPT_DIR/services/$svc/manifests/overlays/ghcr" | oc apply -n "$NAMESPACE" -f -
    done
    
    log "Waiting for services..."
    oc wait --for=condition=Available deployment -l app.kubernetes.io/part-of=advanced-rag -n "$NAMESPACE" --timeout=180s || warn "Some deployments not ready"
}

deploy_mcp() {
    [[ "$SKIP_MCP" == "true" ]] && { warn "Skipping MCP (SKIP_MCP=true)"; return; }
    
    log "Deploying retrieval-mcp..."
    kustomize build "$SCRIPT_DIR/retrieval-mcp/manifests/overlays/ghcr" | oc apply -n "$NAMESPACE" -f -
    oc wait --for=condition=Available deployment/retrieval-mcp -n "$NAMESPACE" --timeout=120s || warn "MCP not ready"
}

show_status() {
    log "Deployment complete!"
    echo ""
    oc get pods -n "$NAMESPACE"
    echo ""
    local DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "apps.example.com")
    echo "Routes: https://{vector-gateway,embedding-service,rerank-service,plan-service,evaluator-service,chunker-service}-${NAMESPACE}.${DOMAIN}"
    echo "MCP:    https://retrieval-mcp-${NAMESPACE}.${DOMAIN}/mcp/"
}

main() {
    echo "=== Advanced RAG Deployment ==="
    check_prerequisites
    setup_namespace
    create_secrets
    deploy_milvus
    deploy_services
    deploy_mcp
    show_status
    log "Done! Deployed to namespace: $NAMESPACE"
}

main "$@"
