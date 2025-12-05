# Services Makefile for Advanced RAG
#
# Deploy all services to OpenShift with: make deploy-all
# Build all services remotely with: make build-all
#
# Prerequisites:
#   - oc login to OpenShift cluster
#   - Secrets already created in target namespace
#
# Usage:
#   make deploy-all                    # Deploy using GHCR images (default)
#   make deploy-all OVERLAY=openshift  # Deploy using OpenShift internal registry
#   make build-all                     # Build all services on ec2-dev
#   make push-all                      # Push all images to OpenShift registry
#   make status                        # Check health of all services
#
# Namespace-agnostic deployment:
#   NAMESPACE=my-rag make deploy-all   # Deploy to custom namespace

SHELL := /bin/bash

# Configuration (can be overridden via environment)
NAMESPACE ?= advanced-rag
OVERLAY ?= ghcr
REGISTRY ?= $(shell oc registry info 2>/dev/null)
TOKEN := $(shell oc whoami -t 2>/dev/null)
REMOTE_HOST ?= ec2-dev
REMOTE_BUILD_DIR ?= ~/builds

# Service definitions
SELF_CONTAINED_SERVICES := chunker plan evaluator
ROOT_CONTEXT_SERVICES := embedding rerank vector-gateway
ALL_SERVICES := $(SELF_CONTAINED_SERVICES) $(ROOT_CONTEXT_SERVICES)

# Service directory mapping
chunker_DIR := chunker_service
plan_DIR := plan_service
evaluator_DIR := evaluator_service
embedding_DIR := embedding_service
rerank_DIR := rerank_service
vector-gateway_DIR := vector_gateway

# OpenShift deployment names
chunker_DEPLOY := chunker-service
plan_DEPLOY := plan-service
evaluator_DEPLOY := evaluator-service
embedding_DEPLOY := embedding-service
rerank_DEPLOY := rerank-service
vector-gateway_DEPLOY := vector-gateway

# Route hostnames
CLUSTER_DOMAIN := $(shell oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null)

.PHONY: all help deploy-all deploy-ghcr rollout-all status pods clean kustomize-check

help:
	@echo "Services Makefile for Advanced RAG"
	@echo ""
	@echo "Quick Start (uses pre-built GHCR images):"
	@echo "  make deploy-all              Deploy all services"
	@echo "  make status                  Check service health"
	@echo ""
	@echo "Configuration (override via environment):"
	@echo "  NAMESPACE   Target namespace (default: $(NAMESPACE))"
	@echo "  OVERLAY     Kustomize overlay: ghcr or openshift (default: $(OVERLAY))"
	@echo ""
	@echo "Deploy Targets:"
	@echo "  make deploy-all              Deploy all services"
	@echo "  make deploy-<svc>            Deploy one service"
	@echo "  make rollout-all             Restart all deployments"
	@echo ""
	@echo "Build Targets (requires ssh to build host):"
	@echo "  make build-all               Build all services"
	@echo "  make push-all                Push to OpenShift registry"
	@echo ""
	@echo "Examples:"
	@echo "  NAMESPACE=my-rag make deploy-all"
	@echo "  OVERLAY=openshift make deploy-all"
	@echo ""
	@echo "Services: $(ALL_SERVICES)"

kustomize-check:
	@command -v kustomize > /dev/null 2>&1 || (echo "ERROR: kustomize not found. Install with: brew install kustomize" && exit 1)

# ============================================================================
# Deploy targets (using Kustomize with GHCR images by default)
# ============================================================================

deploy-all: kustomize-check $(addprefix deploy-,$(ALL_SERVICES))
	@echo "All services deployed to $(NAMESPACE) using $(OVERLAY) overlay"
	@$(MAKE) status

define DEPLOY_TARGET
deploy-$(1): kustomize-check
	@echo "Deploying $(1) to $(NAMESPACE)..."
	@kustomize build $$($(1)_DIR)/manifests/overlays/$(OVERLAY) | oc apply -n $(NAMESPACE) -f -
	@oc rollout restart deployment/$$($(1)_DEPLOY) -n $(NAMESPACE) 2>/dev/null || true
	@oc rollout status deployment/$$($(1)_DEPLOY) -n $(NAMESPACE) --timeout=120s
endef

$(foreach svc,$(ALL_SERVICES),$(eval $(call DEPLOY_TARGET,$(svc))))

# ============================================================================
# Rollout targets
# ============================================================================

rollout-all: $(addprefix rollout-,$(ALL_SERVICES))
	@echo "All services restarted"
	@$(MAKE) status

define ROLLOUT_TARGET
rollout-$(1):
	@oc rollout restart deployment/$$($(1)_DEPLOY) -n $(NAMESPACE)
	@oc rollout status deployment/$$($(1)_DEPLOY) -n $(NAMESPACE) --timeout=120s
endef

$(foreach svc,$(ALL_SERVICES),$(eval $(call ROLLOUT_TARGET,$(svc))))

# ============================================================================
# Status
# ============================================================================

status:
	@echo "Service Health ($(NAMESPACE)):"
	@echo "=============================="
	@for svc in chunker-service plan-service evaluator-service embedding-service rerank-service vector-gateway; do \
		printf "%-20s %s\n" "$$svc:" "$$(curl -sk https://$$svc-$(NAMESPACE).$(CLUSTER_DOMAIN)/healthz 2>/dev/null || echo 'UNREACHABLE')"; \
	done

pods:
	@oc get pods -n $(NAMESPACE) -l app.kubernetes.io/part-of=advanced-rag

logs-%:
	@oc logs -f deployment/$($*_DEPLOY) -n $(NAMESPACE)

# ============================================================================
# Build targets (for custom builds, requires remote host)
# ============================================================================

check-prereqs:
	@oc whoami > /dev/null 2>&1 || (echo "ERROR: Not logged into OpenShift" && exit 1)
	@ssh -q $(REMOTE_HOST) exit 2>/dev/null || (echo "ERROR: Cannot connect to $(REMOTE_HOST)" && exit 1)

login:
	@ssh $(REMOTE_HOST) "podman login --tls-verify=false -u unused -p '$(TOKEN)' '$(REGISTRY)'" 2>&1

build-all: check-prereqs login $(addprefix build-,$(ALL_SERVICES))
	@echo "All services built"

define SELF_CONTAINED_BUILD
build-$(1): check-prereqs
	@rsync -az --delete $$($(1)_DIR)/ $(REMOTE_HOST):$(REMOTE_BUILD_DIR)/$(1)-service/
	@ssh $(REMOTE_HOST) "cd $(REMOTE_BUILD_DIR)/$(1)-service && podman build --platform linux/amd64 -t $(1)-service:latest -f Containerfile ." | tail -5
endef

$(foreach svc,$(SELF_CONTAINED_SERVICES),$(eval $(call SELF_CONTAINED_BUILD,$(svc))))

define ROOT_CONTEXT_BUILD
build-$(1): check-prereqs
	@ssh $(REMOTE_HOST) "mkdir -p $(REMOTE_BUILD_DIR)/$(1)-service"
	@rsync -az --delete rag_core/ $(REMOTE_HOST):$(REMOTE_BUILD_DIR)/$(1)-service/rag_core/
	@rsync -az --delete $$($(1)_DIR)/ $(REMOTE_HOST):$(REMOTE_BUILD_DIR)/$(1)-service/$$($(1)_DIR)/
	@ssh $(REMOTE_HOST) "cd $(REMOTE_BUILD_DIR)/$(1)-service && podman build --platform linux/amd64 -t $(1)-service:latest -f $$($(1)_DIR)/Containerfile ." | tail -5
endef

$(foreach svc,$(ROOT_CONTEXT_SERVICES),$(eval $(call ROOT_CONTEXT_BUILD,$(svc))))

push-all: login $(addprefix push-,$(ALL_SERVICES))
	@echo "All images pushed to $(NAMESPACE)"

define PUSH_TARGET
push-$(1): login
	@ssh $(REMOTE_HOST) "podman tag $(1)-service:latest $(REGISTRY)/$(NAMESPACE)/$(1)-service:latest" 2>/dev/null || true
	@ssh $(REMOTE_HOST) "podman push --tls-verify=false $(REGISTRY)/$(NAMESPACE)/$(1)-service:latest" | tail -3
endef

$(foreach svc,$(ALL_SERVICES),$(eval $(call PUSH_TARGET,$(svc))))

all: build-all push-all deploy-all

clean:
	@ssh $(REMOTE_HOST) "rm -rf $(REMOTE_BUILD_DIR)/*-service" 2>/dev/null || true

# ============================================================================
# Render manifests (for review)
# ============================================================================

render-%: kustomize-check
	@kustomize build $($*_DIR)/manifests/overlays/$(OVERLAY)

render-all: kustomize-check
	@for svc in $(ALL_SERVICES); do echo "--- $$svc ---"; $(MAKE) render-$$svc; done
