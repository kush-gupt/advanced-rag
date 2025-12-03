"""
Example Kubeflow Pipeline for Advanced RAG Ingestion.

This pipeline demonstrates the end-to-end document ingestion flow:
1. Convert PDF to Markdown using docling-serve
2. Generate a chunking plan using plan-service
3. Chunk the text using chunker-service
4. Embed and store chunks using vector-gateway
5. Run a test query to verify ingestion

Each step calls the deployed microservices via HTTP.
"""

import argparse
from pathlib import Path

import kfp
from kfp import dsl


# Default service URLs (OpenShift internal DNS)
DEFAULT_DOCLING_URL = "http://docling-serve.docling-serve.svc.cluster.local:5001"
DEFAULT_PLAN_URL = "http://plan-service.advanced-rag.svc.cluster.local:8000"
DEFAULT_CHUNKER_URL = "http://chunker-service.advanced-rag.svc.cluster.local:8080"
DEFAULT_GATEWAY_URL = "http://vector-gateway.advanced-rag.svc.cluster.local:8005"


@dsl.component(
    base_image="registry.redhat.io/ubi9/python-311:latest",
    packages_to_install=["httpx"],
)
def convert_document(
    pdf_url: str,
    docling_url: str,
    output_markdown: dsl.Output[dsl.Artifact],
) -> str:
    """Convert a PDF document to Markdown using docling-serve."""
    import httpx
    import json
    import time

    # Download PDF
    print(f"Downloading PDF from: {pdf_url}")
    pdf_response = httpx.get(pdf_url, follow_redirects=True, timeout=60.0)
    pdf_response.raise_for_status()
    pdf_content = pdf_response.content
    print(f"Downloaded {len(pdf_content)} bytes")

    # Submit to docling for async conversion
    print(f"Submitting to docling-serve: {docling_url}")
    files = {"files": ("document.pdf", pdf_content, "application/pdf")}
    data = {"from_formats": "pdf", "to_formats": "md"}

    response = httpx.post(
        f"{docling_url}/v1/convert/file/async",
        files=files,
        data=data,
        timeout=30.0,
    )
    response.raise_for_status()
    task_id = response.json()["task_id"]
    print(f"Conversion task ID: {task_id}")

    # Poll for completion
    max_wait = 300  # 5 minutes
    start = time.time()
    while time.time() - start < max_wait:
        status_response = httpx.get(
            f"{docling_url}/v1/status/poll/{task_id}",
            timeout=10.0,
        )
        status = status_response.json().get("task_status", "unknown")
        print(f"Status: {status}")
        if status == "success":
            break
        elif status == "failure":
            raise RuntimeError(f"Docling conversion failed: {status_response.text}")
        time.sleep(5)
    else:
        raise RuntimeError("Docling conversion timed out")

    # Get result
    result_response = httpx.get(
        f"{docling_url}/v1/result/{task_id}",
        timeout=30.0,
    )
    result_response.raise_for_status()

    # Extract markdown from result
    result = result_response.json()
    # Result structure varies; try common paths
    if isinstance(result, dict):
        markdown = result.get("md") or result.get("markdown") or result.get("content", "")
        if not markdown and "document" in result:
            markdown = result["document"].get("md", "")
    else:
        markdown = str(result)

    print(f"Extracted {len(markdown)} characters of markdown")

    # Write output artifact
    with open(output_markdown.path, "w") as f:
        f.write(markdown)

    return markdown


@dsl.component(
    base_image="registry.redhat.io/ubi9/python-311:latest",
    packages_to_install=["httpx"],
)
def generate_plan(
    markdown_text: str,
    plan_url: str,
    file_name: str,
) -> dict:
    """Generate a chunking plan using the plan-service."""
    import httpx
    import json

    print(f"Generating plan via: {plan_url}")
    print(f"Text length: {len(markdown_text)} characters")

    # Send sample of text for plan generation
    sample = markdown_text[:8000] if len(markdown_text) > 8000 else markdown_text

    response = httpx.post(
        f"{plan_url}/plan",
        json={
            "text": sample,
            "meta": {"file_name": file_name, "mime_type": "text/markdown"},
        },
        timeout=60.0,
    )
    response.raise_for_status()
    result = response.json()

    plan = result.get("plan", {})
    print(f"Generated plan: {json.dumps(plan, indent=2)}")
    print(f"Model: {result.get('model')}, Latency: {result.get('latency_ms')}ms")

    return plan


@dsl.component(
    base_image="registry.redhat.io/ubi9/python-311:latest",
    packages_to_install=["httpx"],
)
def chunk_text(
    markdown_text: str,
    plan: dict,
    chunker_url: str,
    file_name: str,
    output_chunks: dsl.Output[dsl.Artifact],
) -> int:
    """Chunk the text using the chunker-service."""
    import httpx
    import json

    print(f"Chunking via: {chunker_url}")
    print(f"Plan: {json.dumps(plan, indent=2)}")

    response = httpx.post(
        f"{chunker_url}/chunk",
        json={
            "text": markdown_text,
            "plan": plan,
            "meta": {"file_name": file_name, "file_path": f"/documents/{file_name}"},
        },
        timeout=120.0,
    )
    response.raise_for_status()
    chunks = response.json()

    print(f"Created {len(chunks)} chunks")

    # Write chunks to artifact
    with open(output_chunks.path, "w") as f:
        json.dump(chunks, f, indent=2)

    return len(chunks)


@dsl.component(
    base_image="registry.redhat.io/ubi9/python-311:latest",
    packages_to_install=["httpx"],
)
def embed_and_store(
    chunks_path: dsl.Input[dsl.Artifact],
    gateway_url: str,
    collection: str,
) -> int:
    """Embed chunks and store in vector database via vector-gateway."""
    import httpx
    import json

    print(f"Storing via: {gateway_url}")
    print(f"Collection: {collection}")

    # Read chunks
    with open(chunks_path.path, "r") as f:
        chunks = json.load(f)

    print(f"Processing {len(chunks)} chunks")

    # Prepare documents for upsert
    documents = []
    for chunk in chunks:
        documents.append({
            "doc_id": chunk.get("chunk_id"),
            "text": chunk.get("text", ""),
            "metadata": {
                "file_name": chunk.get("file_name", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "created_at": chunk.get("created_at", ""),
            },
        })

    # Upsert in batches
    batch_size = 50
    total_inserted = 0
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        response = httpx.post(
            f"{gateway_url}/upsert",
            json={"documents": batch, "collection": collection},
            timeout=120.0,
        )
        response.raise_for_status()
        result = response.json()
        inserted = result.get("inserted", len(batch))
        total_inserted += inserted
        print(f"Batch {i // batch_size + 1}: inserted {inserted} documents")

    print(f"Total inserted: {total_inserted}")
    return total_inserted


@dsl.component(
    base_image="registry.redhat.io/ubi9/python-311:latest",
    packages_to_install=["httpx"],
)
def test_query(
    gateway_url: str,
    collection: str,
    query: str,
    top_k: int,
) -> str:
    """Run a test query to verify ingestion."""
    import httpx
    import json

    print(f"Querying: {gateway_url}")
    print(f"Collection: {collection}")
    print(f"Query: {query}")

    response = httpx.post(
        f"{gateway_url}/search",
        json={
            "query": query,
            "collection": collection,
            "top_k": top_k,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    result = response.json()

    hits = result.get("hits", [])
    print(f"Found {len(hits)} results")

    # Format results
    output_lines = [f"Query: {query}", f"Results: {len(hits)}", ""]
    for i, hit in enumerate(hits):
        score = hit.get("score", 0)
        text = hit.get("text", "")[:200]
        output_lines.append(f"{i + 1}. [Score: {score:.4f}]")
        output_lines.append(f"   {text}...")
        output_lines.append("")

    output = "\n".join(output_lines)
    print(output)
    return output


@dsl.pipeline(
    name="advanced-rag-ingest-example",
    description="Example pipeline: Convert PDF, plan, chunk, embed, and query",
)
def ingest_pipeline(
    pdf_url: str = "https://raw.githubusercontent.com/example/docs/main/sample.pdf",
    collection: str = "example_docs",
    test_query_text: str = "What is this document about?",
    top_k: int = 5,
    docling_url: str = DEFAULT_DOCLING_URL,
    plan_url: str = DEFAULT_PLAN_URL,
    chunker_url: str = DEFAULT_CHUNKER_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
):
    """
    End-to-end RAG ingestion pipeline.

    Args:
        pdf_url: URL to the PDF document to ingest
        collection: Vector store collection name
        test_query_text: Query to run after ingestion
        top_k: Number of results for test query
        docling_url: Docling service URL
        plan_url: Plan service URL
        chunker_url: Chunker service URL
        gateway_url: Vector gateway URL
    """
    # Step 1: Convert PDF to Markdown
    convert_task = convert_document(
        pdf_url=pdf_url,
        docling_url=docling_url,
    )

    # Step 2: Generate chunking plan
    plan_task = generate_plan(
        markdown_text=convert_task.outputs["output"],
        plan_url=plan_url,
        file_name="document.pdf",
    )

    # Step 3: Chunk the text
    chunk_task = chunk_text(
        markdown_text=convert_task.outputs["output"],
        plan=plan_task.output,
        chunker_url=chunker_url,
        file_name="document.pdf",
    )

    # Step 4: Embed and store
    store_task = embed_and_store(
        chunks_path=chunk_task.outputs["output_chunks"],
        gateway_url=gateway_url,
        collection=collection,
    )

    # Step 5: Test query
    query_task = test_query(
        gateway_url=gateway_url,
        collection=collection,
        query=test_query_text,
        top_k=top_k,
    )
    query_task.after(store_task)


def compile_pipeline(output: Path) -> None:
    """Compile the pipeline to YAML."""
    compiler = kfp.compiler.Compiler()
    compiler.compile(
        pipeline_func=ingest_pipeline,
        package_path=str(output),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile the example ingest pipeline")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pipelines/example/ingest_pipeline.yaml"),
        help="Output path for compiled pipeline YAML",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    compile_pipeline(args.output)
    print(f"Compiled pipeline to: {args.output}")
