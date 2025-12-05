#!/bin/bash
# Advanced RAG Deployment Helper
# Simplifies deployment from within the toolbox container

set -e

REPO_URL="${REPO_URL:-https://github.com/redhat-ai-services/advanced-rag.git}"
BRANCH="${BRANCH:-main}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
header() { echo -e "\n${BLUE}=== $1 ===${NC}\n"; }

show_help() {
    cat << 'EOF'
Advanced RAG Deployment Helper

USAGE:
    deploy-helper [COMMAND]

COMMANDS:
    clone       Clone the repository
    deploy      Run full deployment (requires OPENAI_API_KEY)
    status      Show current deployment status
    tools       Show installed tool versions
    help        Show this help message

ENVIRONMENT VARIABLES:
    REPO_URL        Git repository URL (default: https://github.com/redhat-ai-services/advanced-rag.git)
    BRANCH          Git branch to clone (default: main)
    NAMESPACE       Target namespace (default: advanced-rag)
    OPENAI_API_KEY  Required for deployment
    COHERE_API_KEY  Optional, for Cohere reranking
    SKIP_MILVUS     Set to "true" to skip Milvus
    SKIP_SERVICES   Set to "true" to skip services
    SKIP_MCP        Set to "true" to skip MCP server

EXAMPLES:
    # Interactive deployment
    deploy-helper clone
    cd advanced-rag
    export OPENAI_API_KEY="sk-..."
    ./deploy.sh

    # Quick deployment
    export OPENAI_API_KEY="sk-..."
    deploy-helper deploy

    # Check status
    deploy-helper status
EOF
}

check_login() {
    if ! oc whoami &>/dev/null; then
        error "Not logged into OpenShift. Run 'oc login' first."
    fi
    log "Logged in as: $(oc whoami)"
    log "Cluster: $(oc whoami --show-server)"
}

show_tools() {
    header "Installed Tools"
    echo "oc:        $(oc version --client 2>/dev/null | grep 'Client Version' | awk '{print $3}')"
    echo "kubectl:   $(kubectl version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion')"
    echo "helm:      $(helm version --short 2>/dev/null)"
    echo "kustomize: $(kustomize version 2>/dev/null | grep -oP 'v[\d.]+')"
    echo "git:       $(git --version | awk '{print $3}')"
    echo "jq:        $(jq --version)"
}

clone_repo() {
    header "Cloning Repository"
    if [[ -d "advanced-rag" ]]; then
        warn "Directory 'advanced-rag' already exists"
        read -p "Remove and re-clone? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf advanced-rag
        else
            log "Using existing directory"
            return
        fi
    fi
    
    log "Cloning $REPO_URL (branch: $BRANCH)..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL"
    log "Repository cloned to ./advanced-rag"
    echo ""
    echo "Next steps:"
    echo "  cd advanced-rag"
    echo "  export OPENAI_API_KEY='your-key'"
    echo "  ./deploy.sh"
}

run_deploy() {
    header "Running Deployment"
    check_login
    
    if [[ -z "$OPENAI_API_KEY" ]]; then
        error "OPENAI_API_KEY environment variable is required"
    fi
    
    if [[ ! -d "advanced-rag" ]]; then
        clone_repo
    fi
    
    cd advanced-rag
    chmod +x deploy.sh
    ./deploy.sh
}

show_status() {
    header "Deployment Status"
    check_login
    
    NS="${NAMESPACE:-advanced-rag}"
    
    if ! oc get namespace "$NS" &>/dev/null; then
        warn "Namespace '$NS' does not exist"
        return
    fi
    
    echo "Namespace: $NS"
    echo ""
    echo "Pods:"
    oc get pods -n "$NS" 2>/dev/null || echo "  (none)"
    echo ""
    echo "Services:"
    oc get svc -n "$NS" 2>/dev/null || echo "  (none)"
    echo ""
    echo "Routes:"
    oc get routes -n "$NS" 2>/dev/null || echo "  (none)"
}

case "${1:-help}" in
    clone)
        clone_repo
        ;;
    deploy)
        run_deploy
        ;;
    status)
        show_status
        ;;
    tools)
        show_tools
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        error "Unknown command: $1. Run 'deploy-helper help' for usage."
        ;;
esac

