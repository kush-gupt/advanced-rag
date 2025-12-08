#!/bin/bash
# Deploy all-MiniLM-L6-v2 Embedding model using OCI Modelcar (no S3 required)
#
# Prerequisites:
#   - Logged into OpenShift cluster
#   - Modelcar image built and pushed to registry
#
# Usage:
#   ./deploy-minilm-oci.sh [namespace] [registry-owner]
#
# Example:
#   ./deploy-minilm-oci.sh caikit-embeddings myorg

set -e

NAMESPACE="${1:-caikit-embeddings}"
REGISTRY_OWNER="${2:-REGISTRY_OWNER}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Deploying all-MiniLM-L6-v2 Embedding (OCI) to namespace: $NAMESPACE"

if [ "$REGISTRY_OWNER" = "REGISTRY_OWNER" ]; then
    echo "Warning: Using placeholder REGISTRY_OWNER."
    echo "Usage: ./deploy-minilm-oci.sh [namespace] [registry-owner]"
    echo "Example: ./deploy-minilm-oci.sh caikit-embeddings myorg"
    echo ""
fi

# Ensure namespace exists
oc get namespace "$NAMESPACE" >/dev/null 2>&1 || {
    echo "Creating namespace $NAMESPACE..."
    oc new-project "$NAMESPACE" || oc create namespace "$NAMESPACE"
}

# Deploy ServingRuntime if not present
if ! oc get servingruntime caikit-standalone-runtime -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "Deploying ServingRuntime..."
    oc apply -f "$SCRIPT_DIR/manifests/base/serving-runtime.yaml" -n "$NAMESPACE"
fi

# Deploy InferenceService with OCI storage
echo "Deploying InferenceService with OCI modelcar..."
if [ "$REGISTRY_OWNER" != "REGISTRY_OWNER" ]; then
    # Replace the placeholder with actual registry owner
    sed "s/REGISTRY_OWNER/$REGISTRY_OWNER/g" \
        "$SCRIPT_DIR/manifests/minilm-embedding-oci/inference-service.yaml" | \
        oc apply -n "$NAMESPACE" -f -
else
    oc apply -f "$SCRIPT_DIR/manifests/minilm-embedding-oci/inference-service.yaml" -n "$NAMESPACE"
fi

# Wait for deployment
echo "Waiting for deployment to be ready..."
oc wait --for=condition=Ready inferenceservice/all-minilm-l6-v2 -n "$NAMESPACE" --timeout=300s || {
    echo "Timeout waiting for InferenceService. Check pod logs:"
    echo "  oc logs -l serving.kserve.io/inferenceservice=all-minilm-l6-v2 -n $NAMESPACE"
    echo ""
    echo "Check storage initializer logs:"
    echo "  oc logs <pod-name> -c storage-initializer -n $NAMESPACE"
    exit 1
}

# Deploy Service and Route for external access
echo "Creating external route..."
oc apply -f "$SCRIPT_DIR/manifests/minilm-embedding-oci/service.yaml" -n "$NAMESPACE"
oc apply -f "$SCRIPT_DIR/manifests/minilm-embedding-oci/route.yaml" -n "$NAMESPACE"

# Get external endpoint
ROUTE_HOST=$(oc get route all-minilm-l6-v2 -n "$NAMESPACE" -o jsonpath='{.spec.host}')
ENDPOINT="https://$ROUTE_HOST"
echo ""
echo "all-MiniLM-L6-v2 Embedding (OCI) deployed successfully!"
echo "External endpoint: $ENDPOINT"
echo ""
echo "Test with:"
echo "  curl -sk -X POST $ENDPOINT/api/v1/task/embedding \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"model_id\": \"all-minilm-l6-v2\", \"inputs\": \"Hello world\"}'"

