"""List collections or get stats for a specific collection."""

from typing import Annotated, Any

import httpx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.services import (
    get_collection_stats,
    list_collections as service_list_collections,
)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_collections(
    collection: Annotated[
        str | None,
        Field(description="If provided, return detailed stats for this collection"),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Discover available collections or get stats for a specific collection.

    Without a collection parameter, returns a list of all collections with
    document counts. With a collection name, returns detailed statistics
    including file list and chunk counts.
    """
    try:
        # Get list of all collections first
        all_collections = await service_list_collections()
    except ValueError as e:
        raise ToolError(str(e))
    except httpx.HTTPStatusError as e:
        raise ToolError(f"Vector gateway error: {e.response.status_code}")
    except httpx.ConnectError:
        raise ToolError(
            "Cannot connect to vector gateway. "
            "Verify VECTOR_GATEWAY_URL is correct and service is running."
        )

    # If specific collection requested, get stats for it
    if collection:
        if collection not in all_collections:
            available = ", ".join(all_collections) if all_collections else "none"
            raise ToolError(
                f"Collection '{collection}' not found. "
                f"Available collections: {available}. "
                "Use get_collections without parameters to see all collections."
            )

        if ctx:
            await ctx.info(f"Getting stats for collection '{collection}'")

        try:
            stats = await get_collection_stats(collection)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                available = ", ".join(all_collections) if all_collections else "none"
                raise ToolError(
                    f"Collection '{collection}' not found. "
                    f"Available collections: {available}. "
                    "Use get_collections without parameters to see all collections."
                )
            raise ToolError(f"Vector gateway error: {e.response.status_code}")
        except httpx.ConnectError:
            raise ToolError(
                "Cannot connect to vector gateway. "
                "Verify VECTOR_GATEWAY_URL is correct and service is running."
            )

        # Vector gateway returns row_count and file_names
        document_count = stats.get("row_count", stats.get("document_count", 0))
        files = stats.get("file_names", stats.get("files", []))
        file_count = len(files)

        return {
            "name": collection,
            "document_count": document_count,
            "files": files,
            "file_count": file_count,
            "message": f"Collection '{collection}' contains {document_count} chunks from {file_count} files",
        }

    # No collection specified - return list mode
    if ctx:
        await ctx.info("Listing all collections")

    # Get stats for each collection
    collections_with_stats = []
    total_documents = 0

    for coll_name in all_collections:
        try:
            stats = await get_collection_stats(coll_name)
            # Vector gateway returns row_count
            doc_count = stats.get("row_count", stats.get("document_count", 0))
        except Exception:
            # If we can't get stats, still include collection with 0 count
            doc_count = 0

        collections_with_stats.append({
            "name": coll_name,
            "document_count": doc_count,
        })
        total_documents += doc_count

    return {
        "collections": collections_with_stats,
        "total_collections": len(all_collections),
        "message": f"Found {len(all_collections)} collections with {total_documents} total documents",
    }