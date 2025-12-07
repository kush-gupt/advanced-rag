#!/bin/bash
set -e

REPO_URL="${REPO_URL:-https://github.com/kush-gupt/advanced-rag.git}"
BRANCH="${BRANCH:-main}"

log() { echo -e "\033[0;32m[INFO]\033[0m $1"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $1"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; exit 1; }

show_help() {
    cat << 'EOF'
Usage: deploy-helper [COMMAND]

Commands:
    clone       Clone the repository
    deploy      Run full deployment (requires OPENAI_API_KEY)
    status      Show current deployment status
    tools       Show installed tool versions
    help        Show this help message

Environment Variables:
    REPO_URL        Git repository URL
    BRANCH          Git branch (default: main)
    NAMESPACE       Target namespace (default: advanced-rag)
    OPENAI_API_KEY  Required for deployment
    COHERE_API_KEY  Optional, for Cohere reranking
    SKIP_MILVUS     Skip Milvus deployment
    SKIP_SERVICES   Skip services deployment
    SKIP_MCP        Skip MCP server deployment
EOF
}

check_login() {
    oc whoami &>/dev/null || error "Not logged into OpenShift. Run 'oc login' first."
    log "Logged in as: $(oc whoami) on $(oc whoami --show-server)"
}

show_tools() {
    echo "oc:        $(oc version --client 2>/dev/null | grep 'Client Version' | awk '{print $3}')"
    echo "kubectl:   $(kubectl version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion')"
    echo "helm:      $(helm version --short 2>/dev/null)"
    echo "kustomize: $(kustomize version 2>/dev/null | grep -oP 'v[\d.]+')"
    echo "git:       $(git --version | awk '{print $3}')"
    echo "jq:        $(jq --version)"
}

clone_repo() {
    if [[ -d "advanced-rag" ]]; then
        warn "Directory 'advanced-rag' already exists"
        read -p "Remove and re-clone? [y/N] " -n 1 -r
        echo
        [[ $REPLY =~ ^[Yy]$ ]] && rm -rf advanced-rag || { log "Using existing directory"; return; }
    fi
    log "Cloning $REPO_URL (branch: $BRANCH)..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL"
    log "Done. Run: cd advanced-rag && export OPENAI_API_KEY='...' && ./deploy.sh"
}

run_deploy() {
    check_login
    [[ -n "$OPENAI_API_KEY" ]] || error "OPENAI_API_KEY environment variable is required"
    [[ -d "advanced-rag" ]] || clone_repo
    cd advanced-rag
    chmod +x deploy.sh
    ./deploy.sh
}

show_status() {
    check_login
    NS="${NAMESPACE:-advanced-rag}"
    oc get namespace "$NS" &>/dev/null || { warn "Namespace '$NS' does not exist"; return; }
    echo "Namespace: $NS"
    echo -e "\nPods:" && oc get pods -n "$NS" 2>/dev/null || echo "  (none)"
    echo -e "\nServices:" && oc get svc -n "$NS" 2>/dev/null || echo "  (none)"
    echo -e "\nRoutes:" && oc get routes -n "$NS" 2>/dev/null || echo "  (none)"
}

case "${1:-help}" in
    clone) clone_repo ;;
    deploy) run_deploy ;;
    status) show_status ;;
    tools) show_tools ;;
    help|--help|-h) show_help ;;
    *) error "Unknown command: $1. Run 'deploy-helper help' for usage." ;;
esac
