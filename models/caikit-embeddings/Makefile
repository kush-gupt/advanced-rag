# Caikit Embeddings and Reranker Deployment
#
# Usage:
#   make help                    - Show available targets
#   make deploy-minilm           - Deploy MiniLM embedding model
#   make deploy-granite          - Deploy Granite embedding model
#   make deploy-reranker         - Deploy MS-MARCO reranker model
#   make deploy-all              - Deploy all models
#
# Prerequisites:
#   - Logged into OpenShift cluster (oc login)
#   - Models bootstrapped and uploaded to S3 (see bootstrap-* and upload-* targets)
#   - Data connection secret exists (aws-connection-model-storage)

NAMESPACE ?= caikit-embeddings
SCRIPT_DIR := scripts
MANIFEST_DIR := manifests

.PHONY: help
help:
	@echo "Caikit Model Deployment"
	@echo ""
	@echo "DEPLOYMENT TARGETS (S3 storage - run from OpenShift client machine):"
	@echo "  make deploy-minilm      Deploy all-MiniLM-L6-v2 embedding (384 dims)"
	@echo "  make deploy-granite     Deploy Granite embedding 278M (768 dims)"
	@echo "  make deploy-reranker    Deploy MS-MARCO MiniLM reranker"
	@echo "  make deploy-all         Deploy all three models"
	@echo ""
	@echo "DEPLOYMENT TARGETS (OCI Modelcar - no S3 required):"
	@echo "  make deploy-minilm-oci  Deploy MiniLM using OCI modelcar"
	@echo "  make deploy-reranker-oci Deploy reranker using OCI modelcar"
	@echo "  make deploy-all-oci     Deploy MiniLM + reranker using OCI modelcars"
	@echo ""
	@echo "MODELCAR BUILD TARGETS (local build):"
	@echo "  make build-minilm-modelcar   Build MiniLM modelcar image locally"
	@echo "  make build-reranker-modelcar Build reranker modelcar image locally"
	@echo "  make build-all-modelcars     Build all modelcar images locally"
	@echo ""
	@echo "INFRASTRUCTURE TARGETS:"
	@echo "  make setup-namespace    Create namespace and apply base resources"
	@echo "  make status             Show deployment status of all models"
	@echo "  make logs-minilm        Show logs for MiniLM deployment"
	@echo "  make logs-granite       Show logs for Granite deployment"
	@echo "  make logs-reranker      Show logs for reranker deployment"
	@echo ""
	@echo "BOOTSTRAP TARGETS (run in OpenShift AI Workbench - for S3 method):"
	@echo "  make bootstrap-minilm   Bootstrap MiniLM model from HuggingFace"
	@echo "  make bootstrap-granite  Bootstrap Granite model from HuggingFace"
	@echo "  make bootstrap-reranker Bootstrap MS-MARCO reranker from HuggingFace"
	@echo ""
	@echo "UPLOAD TARGETS (run in OpenShift AI Workbench after bootstrap):"
	@echo "  make upload-minilm      Upload MiniLM to S3 with correct structure"
	@echo "  make upload-granite     Upload Granite to S3 with correct structure"
	@echo "  make upload-reranker    Upload reranker to S3 with correct structure"
	@echo ""
	@echo "TEST TARGETS:"
	@echo "  make test-minilm        Test MiniLM embedding endpoint"
	@echo "  make test-granite       Test Granite embedding endpoint"
	@echo "  make test-reranker      Test reranker endpoint"
	@echo "  make test-all           Test all endpoints"
	@echo ""
	@echo "CLEANUP TARGETS:"
	@echo "  make undeploy-minilm    Remove MiniLM deployment"
	@echo "  make undeploy-granite   Remove Granite deployment"
	@echo "  make undeploy-reranker  Remove reranker deployment"
	@echo "  make undeploy-all       Remove all deployments"
	@echo ""
	@echo "OPTIONS:"
	@echo "  NAMESPACE=<ns>          Override default namespace (default: caikit-embeddings)"
	@echo "  REGISTRY_OWNER=<owner>  GitHub org/user for modelcar images (required for OCI deploy)"

# =============================================================================
# INFRASTRUCTURE
# =============================================================================

.PHONY: setup-namespace
setup-namespace:
	@echo "Setting up namespace $(NAMESPACE)..."
	@oc get namespace $(NAMESPACE) >/dev/null 2>&1 || oc new-project $(NAMESPACE)
	@echo "Applying ServingRuntime..."
	@oc apply -f $(MANIFEST_DIR)/base/serving-runtime.yaml -n $(NAMESPACE)
	@echo "Checking for data connection secret..."
	@oc get secret aws-connection-model-storage -n $(NAMESPACE) >/dev/null 2>&1 || \
		(echo "WARNING: Secret 'aws-connection-model-storage' not found. Create it before deploying models." && \
		 echo "See: oc apply -f $(MANIFEST_DIR)/base/data-connection-secret.yaml -n $(NAMESPACE)")

.PHONY: status
status:
	@echo "=== Deployment Status in $(NAMESPACE) ==="
	@echo ""
	@echo "ServingRuntime:"
	@oc get servingruntime -n $(NAMESPACE) 2>/dev/null || echo "  No ServingRuntime found"
	@echo ""
	@echo "InferenceServices:"
	@oc get inferenceservice -n $(NAMESPACE) 2>/dev/null || echo "  No InferenceServices found"
	@echo ""
	@echo "Pods:"
	@oc get pods -n $(NAMESPACE) 2>/dev/null || echo "  No pods found"

# =============================================================================
# DEPLOYMENT TARGETS
# =============================================================================

.PHONY: deploy-minilm
deploy-minilm: setup-namespace
	@echo "Deploying all-MiniLM-L6-v2..."
	@./deploy-minilm-embedding.sh $(NAMESPACE)

.PHONY: deploy-granite
deploy-granite: setup-namespace
	@echo "Deploying Granite Embedding 278M..."
	@./deploy-granite-embedding.sh $(NAMESPACE)

.PHONY: deploy-reranker
deploy-reranker: setup-namespace
	@echo "Deploying MS-MARCO Reranker..."
	@./deploy-reranker.sh $(NAMESPACE)

.PHONY: deploy-all
deploy-all: deploy-minilm deploy-granite deploy-reranker
	@echo ""
	@echo "All models deployed. Check status with: make status"

# =============================================================================
# OCI MODELCAR DEPLOYMENT TARGETS (no S3 required)
# =============================================================================

REGISTRY_OWNER ?= REGISTRY_OWNER
MODELCAR_DIR := modelcars

.PHONY: deploy-minilm-oci
deploy-minilm-oci: setup-namespace
	@echo "Deploying all-MiniLM-L6-v2 using OCI modelcar..."
	@./deploy-minilm-oci.sh $(NAMESPACE) $(REGISTRY_OWNER)

.PHONY: deploy-reranker-oci
deploy-reranker-oci: setup-namespace
	@echo "Deploying MS-MARCO Reranker using OCI modelcar..."
	@./deploy-reranker-oci.sh $(NAMESPACE) $(REGISTRY_OWNER)

.PHONY: deploy-all-oci
deploy-all-oci: deploy-minilm-oci deploy-reranker-oci
	@echo ""
	@echo "All OCI-based models deployed. Check status with: make status"

# =============================================================================
# MODELCAR BUILD TARGETS (local build with podman/docker)
# =============================================================================

CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || echo docker)
MODELCAR_REGISTRY ?= ghcr.io/$(REGISTRY_OWNER)/advanced-rag

.PHONY: build-minilm-modelcar
build-minilm-modelcar:
	@echo "Building MiniLM embedding modelcar..."
	@echo "This may take several minutes to download and convert the model."
	$(CONTAINER_ENGINE) build -t $(MODELCAR_REGISTRY)/minilm-embedding-modelcar:latest \
		$(MODELCAR_DIR)/minilm-embedding

.PHONY: build-reranker-modelcar
build-reranker-modelcar:
	@echo "Building reranker modelcar..."
	@echo "This may take several minutes to download and convert the model."
	$(CONTAINER_ENGINE) build -t $(MODELCAR_REGISTRY)/reranker-modelcar:latest \
		$(MODELCAR_DIR)/reranker

.PHONY: build-all-modelcars
build-all-modelcars: build-minilm-modelcar build-reranker-modelcar
	@echo ""
	@echo "All modelcars built. Push with:"
	@echo "  $(CONTAINER_ENGINE) push $(MODELCAR_REGISTRY)/minilm-embedding-modelcar:latest"
	@echo "  $(CONTAINER_ENGINE) push $(MODELCAR_REGISTRY)/reranker-modelcar:latest"

.PHONY: push-minilm-modelcar
push-minilm-modelcar:
	@echo "Pushing MiniLM modelcar..."
	$(CONTAINER_ENGINE) push $(MODELCAR_REGISTRY)/minilm-embedding-modelcar:latest

.PHONY: push-reranker-modelcar
push-reranker-modelcar:
	@echo "Pushing reranker modelcar..."
	$(CONTAINER_ENGINE) push $(MODELCAR_REGISTRY)/reranker-modelcar:latest

.PHONY: push-all-modelcars
push-all-modelcars: push-minilm-modelcar push-reranker-modelcar
	@echo "All modelcars pushed."

# =============================================================================
# BOOTSTRAP TARGETS (run in OpenShift AI Workbench)
# =============================================================================

.PHONY: bootstrap-minilm
bootstrap-minilm:
	@echo "Bootstrapping all-MiniLM-L6-v2..."
	@python $(SCRIPT_DIR)/bootstrap_minilm_embedding.py

.PHONY: bootstrap-granite
bootstrap-granite:
	@echo "Bootstrapping Granite Embedding 278M..."
	@python $(SCRIPT_DIR)/bootstrap_granite_embedding.py

.PHONY: bootstrap-reranker
bootstrap-reranker:
	@echo "Bootstrapping MS-MARCO Reranker..."
	@python $(SCRIPT_DIR)/bootstrap_reranker.py

# =============================================================================
# UPLOAD TARGETS (run in OpenShift AI Workbench after bootstrap)
# =============================================================================

.PHONY: upload-minilm
upload-minilm:
	@echo "Uploading all-MiniLM-L6-v2 to S3..."
	@python $(SCRIPT_DIR)/upload_minilm_to_s3.py

.PHONY: upload-granite
upload-granite:
	@echo "Uploading Granite Embedding 278M to S3..."
	@python $(SCRIPT_DIR)/upload_granite_to_s3.py

.PHONY: upload-reranker
upload-reranker:
	@echo "Uploading MS-MARCO Reranker to S3..."
	@python $(SCRIPT_DIR)/upload_reranker_to_s3.py

# =============================================================================
# TEST TARGETS
# =============================================================================

.PHONY: test-minilm
test-minilm:
	@echo "Testing MiniLM embedding endpoint..."
	@ROUTE_HOST=$$(oc get route all-minilm-l6-v2 -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null) && \
	if [ -z "$$ROUTE_HOST" ]; then \
		echo "ERROR: MiniLM route not found. Deploy with: make deploy-minilm"; \
		exit 1; \
	fi && \
	ENDPOINT="https://$$ROUTE_HOST" && \
	echo "Endpoint: $$ENDPOINT" && \
	curl -sk -X POST "$$ENDPOINT/api/v1/task/embedding" \
		-H "Content-Type: application/json" \
		-d '{"model_id": "all-minilm-l6-v2", "inputs": "Hello world"}' | python3 -c "import sys,json; r=json.load(sys.stdin); print(f'Dimensions: {len(r[\"result\"][\"data\"][\"values\"])}')"

.PHONY: test-granite
test-granite:
	@echo "Testing Granite embedding endpoint..."
	@ROUTE_HOST=$$(oc get route granite-embedding-278m -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null) && \
	if [ -z "$$ROUTE_HOST" ]; then \
		echo "ERROR: Granite route not found. Deploy with: make deploy-granite"; \
		exit 1; \
	fi && \
	ENDPOINT="https://$$ROUTE_HOST" && \
	echo "Endpoint: $$ENDPOINT" && \
	curl -sk -X POST "$$ENDPOINT/api/v1/task/embedding" \
		-H "Content-Type: application/json" \
		-d '{"model_id": "granite-embedding-278m", "inputs": "Hello world"}' | python3 -c "import sys,json; r=json.load(sys.stdin); print(f'Dimensions: {len(r[\"result\"][\"data\"][\"values\"])}')"

.PHONY: test-reranker
test-reranker:
	@echo "Testing MS-MARCO reranker endpoint..."
	@ROUTE_HOST=$$(oc get route ms-marco-reranker -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null) && \
	if [ -z "$$ROUTE_HOST" ]; then \
		echo "ERROR: Reranker route not found. Deploy with: make deploy-reranker"; \
		exit 1; \
	fi && \
	ENDPOINT="https://$$ROUTE_HOST" && \
	echo "Endpoint: $$ENDPOINT" && \
	curl -sk -X POST "$$ENDPOINT/api/v1/task/rerank" \
		-H "Content-Type: application/json" \
		-d '{"model_id": "ms-marco-reranker", "inputs": {"query": "What is ML?", "documents": [{"text": "Machine learning is AI"}, {"text": "The weather is nice"}]}}' | python3 -c "import sys,json; r=json.load(sys.stdin); scores=r['result']['scores']; print(f'Top result: {scores[0][\"text\"]} (score: {scores[0][\"score\"]:.2f})')"

.PHONY: test-all
test-all: test-minilm test-granite test-reranker
	@echo ""
	@echo "All tests complete."

# =============================================================================
# LOG TARGETS
# =============================================================================

.PHONY: logs-minilm
logs-minilm:
	@oc logs -l serving.kserve.io/inferenceservice=all-minilm-l6-v2 -n $(NAMESPACE) --tail=50

.PHONY: logs-granite
logs-granite:
	@oc logs -l serving.kserve.io/inferenceservice=granite-embedding-278m -n $(NAMESPACE) --tail=50

.PHONY: logs-reranker
logs-reranker:
	@oc logs -l serving.kserve.io/inferenceservice=ms-marco-reranker -n $(NAMESPACE) --tail=50

# =============================================================================
# CLEANUP TARGETS
# =============================================================================

.PHONY: undeploy-minilm
undeploy-minilm:
	@echo "Removing MiniLM deployment..."
	@oc delete inferenceservice all-minilm-l6-v2 -n $(NAMESPACE) --ignore-not-found

.PHONY: undeploy-granite
undeploy-granite:
	@echo "Removing Granite deployment..."
	@oc delete inferenceservice granite-embedding-278m -n $(NAMESPACE) --ignore-not-found

.PHONY: undeploy-reranker
undeploy-reranker:
	@echo "Removing reranker deployment..."
	@oc delete inferenceservice ms-marco-reranker -n $(NAMESPACE) --ignore-not-found

.PHONY: undeploy-all
undeploy-all: undeploy-minilm undeploy-granite undeploy-reranker
	@echo "All models removed."
