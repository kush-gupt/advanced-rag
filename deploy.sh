#!/bin/bash
# Advanced RAG - OpenShift Deployment Script
# Deploys all components using pre-built GHCR images
#
# Usage:
#   export OPENAI_API_KEY="your-key"
#   ./deploy.sh
#
# Options:
#   NAMESPACE       Target namespace (default: advanced-rag)
#   OPENAI_API_KEY  Required: API key for LLM services
#   COHERE_API_KEY  Optional: API key for Cohere reranking
#   SKIP_MILVUS     Set to "true" to skip Milvus deployment
#   SKIP_SERVICES   Set to "true" to skip service deployment
#   SKIP_MCP        Set to "true" to skip MCP server deployment

set -e

RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' NC='\033[0m'
log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

NAMESPACE="${NAMESPACE:-advanced-rag}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_prerequisites() {
    log "Checking prerequisites..."
    command -v oc >/dev/null 2>&1 || error "oc CLI not found. Please install OpenShift CLI."
    command -v kustomize >/dev/null 2>&1 || error "kustomize not found. Install with: brew install kustomize"
    [[ "$SKIP_MILVUS" == "true" ]] || command -v helm >/dev/null 2>&1 || error "helm not found. Install with: brew install helm"
    oc whoami >/dev/null 2>&1 || error "Not logged into OpenShift. Run 'oc login' first."
    [[ -n "$OPENAI_API_KEY" ]] || error "OPENAI_API_KEY environment variable is required"
    log "Prerequisites OK"
}

setup_namespace() {
    log "Setting up namespace: $NAMESPACE"
    oc new-project "$NAMESPACE" 2>/dev/null || oc project "$NAMESPACE"
}

create_secrets() {
    log "Creating secrets..."
    
    local COHERE_KEY="${COHERE_API_KEY:-$OPENAI_API_KEY}"
    
    # Embedding service
    oc create secret generic embedding-service-secrets \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Plan service
    oc create secret generic plan-service-secrets \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Evaluator service
    oc create secret generic evaluator-service-secrets \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Vector gateway
    oc create secret generic vector-gateway-secrets \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    # Rerank service
    oc create secret generic rerank-service-secrets \
        --from-literal=COHERE_API_KEY="$COHERE_KEY" \
        --from-literal=RERANK_API_KEY="$COHERE_KEY" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
    
    log "Secrets created"
}

deploy_milvus() {
    if [[ "$SKIP_MILVUS" == "true" ]]; then
        warn "Skipping Milvus deployment (SKIP_MILVUS=true)"
        return
    fi
    
    log "Deploying Milvus..."
    
    # Add Helm repo
    helm repo add zilliztech https://zilliztech.github.io/milvus-helm/ 2>/dev/null || true
    helm repo update
    
    # Install/upgrade Milvus with OpenShift-compatible security settings
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
        log "Milvus already installed, upgrading..."
        helm upgrade milvus zilliztech/milvus "${HELM_ARGS[@]}" -n "$NAMESPACE"
    else
        helm install milvus zilliztech/milvus "${HELM_ARGS[@]}" -n "$NAMESPACE"
    fi
    
    log "Waiting for Milvus to be ready (this may take 2-5 minutes)..."
    oc wait --for=condition=Ready pods -l app.kubernetes.io/name=milvus -n "$NAMESPACE" --timeout=300s || warn "Milvus pods not ready yet, continuing..."
}

deploy_services() {
    if [[ "$SKIP_SERVICES" == "true" ]]; then
        warn "Skipping services deployment (SKIP_SERVICES=true)"
        return
    fi
    
    log "Deploying services..."
    
    local services=(
        "chunker_service"
        "embedding_service"
        "evaluator_service"
        "plan_service"
        "rerank_service"
        "vector_gateway"
    )
    
    for svc in "${services[@]}"; do
        log "  Deploying $svc..."
        kustomize build "$SCRIPT_DIR/services/$svc/manifests/overlays/ghcr" | oc apply -n "$NAMESPACE" -f -
    done
    
    log "Waiting for services to be ready..."
    oc wait --for=condition=Available deployment -l app.kubernetes.io/part-of=advanced-rag -n "$NAMESPACE" --timeout=180s || warn "Some deployments not ready yet"
}

deploy_mcp() {
    if [[ "$SKIP_MCP" == "true" ]]; then
        warn "Skipping MCP server deployment (SKIP_MCP=true)"
        return
    fi
    
    log "Deploying retrieval-mcp..."
    kustomize build "$SCRIPT_DIR/retrieval-mcp/manifests/overlays/ghcr" | oc apply -n "$NAMESPACE" -f -
    
    oc wait --for=condition=Available deployment/retrieval-mcp -n "$NAMESPACE" --timeout=120s || warn "MCP server not ready yet"
}

show_status() {
    log "Deployment complete!"
    echo ""
    echo "=== Pods ==="
    oc get pods -n "$NAMESPACE"
    echo ""
    echo "=== Routes ==="
    oc get routes -n "$NAMESPACE"
    echo ""
    
    local CLUSTER_DOMAIN
    CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "apps.example.com")
    
    echo "=== Service URLs ==="
    echo "  Vector Gateway:    https://vector-gateway-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Embedding Service: https://embedding-service-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Rerank Service:    https://rerank-service-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Plan Service:      https://plan-service-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Evaluator Service: https://evaluator-service-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Chunker Service:   https://chunker-service-${NAMESPACE}.${CLUSTER_DOMAIN}"
    echo "  Retrieval MCP:     https://retrieval-mcp-${NAMESPACE}.${CLUSTER_DOMAIN}/mcp/"
    echo ""
}

main() {
    echo "=============================================="
    echo "  Advanced RAG - OpenShift Deployment"
    echo "=============================================="
    echo ""
    
    check_prerequisites
    setup_namespace
    create_secrets
    deploy_milvus
    deploy_services
    deploy_mcp
    show_status
    
    log "Done! Your Advanced RAG pipeline is deployed to namespace: $NAMESPACE"
}

main "$@"
