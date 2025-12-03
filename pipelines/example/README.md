# Example Kubeflow Pipeline

This directory contains an example Kubeflow Pipeline that demonstrates the end-to-end Advanced RAG ingestion workflow.

## Pipeline Steps

1. **Convert Document** - Sends a PDF to docling-serve for conversion to Markdown
2. **Generate Plan** - Uses plan-service to create an LLM-generated chunking plan
3. **Chunk Text** - Sends text to chunker-service for semantic chunking
4. **Embed & Store** - Embeds chunks and stores them via vector-gateway
5. **Test Query** - Runs a verification query to confirm ingestion succeeded

## Prerequisites

- Kubeflow Pipelines installed on your OpenShift cluster
- All Advanced RAG services deployed (see root README.md)
- `kfp` Python package installed locally for compilation

## Compile the Pipeline

```bash
cd /path/to/advanced-rag

# Install kfp if needed
pip install kfp

# Compile to YAML
python pipelines/example/pipeline.py --output pipelines/example/ingest_pipeline.yaml
```

## Run the Pipeline

### Option 1: Upload to Kubeflow UI

1. Open Kubeflow Pipelines UI
2. Click "Upload Pipeline"
3. Select `ingest_pipeline.yaml`
4. Create a run with your parameters

### Option 2: Run via Python SDK

```python
import kfp
from kfp.client import Client

# Connect to Kubeflow
client = Client(host="https://kubeflow.your-cluster.com")

# Create a run
run = client.create_run_from_pipeline_package(
    "pipelines/example/ingest_pipeline.yaml",
    arguments={
        "pdf_url": "https://example.com/document.pdf",
        "collection": "my_documents",
        "test_query_text": "What is this document about?",
    },
)
print(f"Run ID: {run.run_id}")
```

## Pipeline Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pdf_url` | - | URL to the PDF document to ingest |
| `collection` | `example_docs` | Vector store collection name |
| `test_query_text` | `What is this document about?` | Query to verify ingestion |
| `top_k` | `5` | Number of results for test query |
| `docling_url` | Internal DNS | Docling service URL |
| `plan_url` | Internal DNS | Plan service URL |
| `chunker_url` | Internal DNS | Chunker service URL |
| `gateway_url` | Internal DNS | Vector gateway URL |

## Using External Service URLs

If your services are exposed via OpenShift Routes, override the URL parameters:

```python
arguments={
    "pdf_url": "https://example.com/document.pdf",
    "collection": "my_documents",
    "docling_url": "https://docling-serve-docling-serve.apps.your-cluster.com",
    "plan_url": "https://plan-service-advanced-rag.apps.your-cluster.com",
    "chunker_url": "https://chunker-service-advanced-rag.apps.your-cluster.com",
    "gateway_url": "https://vector-gateway-advanced-rag.apps.your-cluster.com",
}
```

## Testing with Sample Data

Use the included sample PDF (`test_data/drylab.pdf`):

```bash
# First, make the sample available via URL (e.g., upload to S3 or serve locally)
# Then run the pipeline with that URL as pdf_url parameter
```

Or modify the pipeline to accept a local file path if running with local execution.

## Local Execution (Development)

For local testing without Kubeflow:

```python
from kfp import local

# Initialize local runner
local.init(runner=local.SubprocessRunner())

# Import and run pipeline
from pipeline import ingest_pipeline

# Run with test parameters
result = ingest_pipeline(
    pdf_url="https://example.com/test.pdf",
    collection="test_collection",
)
```

## Troubleshooting

### Pipeline step fails to connect to service

- Verify services are running: `oc get pods -n advanced-rag`
- Check service URLs match your deployment
- For external URLs, ensure Routes are created

### Docling conversion times out

- Increase timeout in `convert_document` component
- Check docling-serve logs: `oc logs -f deployment/docling-serve -n docling-serve`

### Embedding fails

- Verify embedding service has API keys configured
- Check vector-gateway logs: `oc logs -f deployment/vector-gateway -n advanced-rag`
