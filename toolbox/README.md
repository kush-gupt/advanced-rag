# Advanced RAG Deployment Toolbox

A container image with all CLI tools needed to deploy Advanced RAG to any OpenShift cluster, including restricted/air-gapped environments.

## Pre-installed Tools

| Tool | Version | Purpose |
|------|---------|---------|
| `oc` | 4.16.x | OpenShift CLI |
| `kubectl` | 4.16.x | Kubernetes CLI |
| `helm` | 3.16.x | Helm package manager |
| `kustomize` | 5.4.x | Kubernetes manifest customization |
| `git` | latest | Clone repositories |
| `jq` | latest | JSON processing |

## Quick Start

### Option 1: Run as a Pod (Recommended)

```bash
# Start the toolbox pod
oc run toolbox \
  --image=ghcr.io/redhat-ai-services/advanced-rag/toolbox:latest \
  -it --rm \
  --restart=Never \
  -- bash

# Inside the toolbox:
deploy-helper clone
cd advanced-rag
export OPENAI_API_KEY="your-key"
./deploy.sh
```

### Option 2: One-liner Deployment

```bash
oc run toolbox \
  --image=ghcr.io/redhat-ai-services/advanced-rag/toolbox:latest \
  -it --rm \
  --restart=Never \
  --env="OPENAI_API_KEY=your-key" \
  -- deploy-helper deploy
```

### Option 3: Local Container

```bash
# Pull and run locally
podman run -it --rm \
  -e OPENAI_API_KEY="your-key" \
  ghcr.io/redhat-ai-services/advanced-rag/toolbox:latest

# Inside container, login and deploy
oc login https://api.your-cluster.com:6443 --token=sha256~...
deploy-helper deploy
```

## Helper Script

The toolbox includes a `deploy-helper` script for common operations:

```bash
# Show available commands
deploy-helper help

# Clone the repository
deploy-helper clone

# Run full deployment
deploy-helper deploy

# Check deployment status
deploy-helper status

# Show installed tool versions
deploy-helper tools
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | API key for LLM services |
| `COHERE_API_KEY` | No | - | API key for Cohere reranking |
| `NAMESPACE` | No | `advanced-rag` | Target namespace |
| `REPO_URL` | No | GitHub URL | Git repository to clone |
| `BRANCH` | No | `main` | Git branch to use |
| `SKIP_MILVUS` | No | `false` | Skip Milvus deployment |
| `SKIP_SERVICES` | No | `false` | Skip services deployment |
| `SKIP_MCP` | No | `false` | Skip MCP server deployment |

## Air-Gapped Deployments

For clusters without internet access:

1. **Mirror the toolbox image** to your internal registry:
   ```bash
   skopeo copy \
     docker://ghcr.io/redhat-ai-services/advanced-rag/toolbox:latest \
     docker://registry.internal.example.com/advanced-rag/toolbox:latest
   ```

2. **Mirror all service images**:
   ```bash
   for svc in chunker-service embedding-service evaluator-service plan-service rerank-service vector-gateway retrieval-mcp; do
     skopeo copy \
       docker://ghcr.io/redhat-ai-services/advanced-rag/${svc}:latest \
       docker://registry.internal.example.com/advanced-rag/${svc}:latest
   done
   ```

3. **Run toolbox with internal registry**:
   ```bash
   oc run toolbox \
     --image=registry.internal.example.com/advanced-rag/toolbox:latest \
     -it --rm \
     -- bash
   ```

4. **Update image references** in the manifests (or create a custom overlay).

## Building Locally

```bash
cd toolbox
podman build -t advanced-rag-toolbox:latest .

# Test it
podman run -it --rm advanced-rag-toolbox:latest deploy-helper tools
```

## Security Notes

- The container runs as non-root (UID 1001) by default
- Compatible with OpenShift's random UID assignment
- Based on UBI9 minimal for security and compliance
- No privileged access required

