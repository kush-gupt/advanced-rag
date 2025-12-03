# Pipelines

This directory contains Kubeflow Pipelines for orchestrating RAG workflows on OpenShift.

## Available Pipelines

| Pipeline | Description |
|----------|-------------|
| [example/](example/) | Example ingest pipeline: PDF → Docling → Plan → Chunk → Embed → Query |

## Prerequisites

- Kubeflow Pipelines installed on OpenShift
- Advanced RAG services deployed (see root README.md)
- Python 3.11+ with `kfp` package for compilation

## Quick Start

```bash
# Install kfp
pip install kfp

# Compile a pipeline
python pipelines/example/pipeline.py

# Output: pipelines/example/ingest_pipeline.yaml
```

## Project Structure

```
pipelines/
├── README.md              # This file
└── example/               # Example ingest pipeline
    ├── pipeline.py        # Pipeline definition
    ├── README.md          # Pipeline documentation
    └── ingest_pipeline.yaml  # Compiled pipeline (generated)
```

## Adding New Pipelines

1. Create a new directory under `pipelines/`
2. Define your pipeline in `pipeline.py`
3. Add compilation logic in `__main__`
4. Create a README documenting parameters and usage
