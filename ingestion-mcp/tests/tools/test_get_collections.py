"""Tests for get_collections tool."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from src.tools.get_collections import get_collections

# Access the underlying function for testing (FastMCP decorator pattern)
get_collections_fn = get_collections.fn


class TestListMode:
    """Tests for listing all collections."""

    @pytest.mark.asyncio
    async def test_list_empty_collections(self):
        """Empty collections list should return properly formatted response."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list:
            mock_list.return_value = []

            result = await get_collections_fn()

            assert result["collections"] == []
            assert result["total_collections"] == 0
            assert "0 collections" in result["message"]

    @pytest.mark.asyncio
    async def test_list_multiple_collections(self):
        """Multiple collections should all be returned with stats."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list, \
             patch("src.tools.get_collections.get_collection_stats") as mock_stats:

            mock_list.return_value = ["rag_gateway", "legal_docs"]
            mock_stats.side_effect = [
                {"document_count": 100},
                {"document_count": 50},
            ]

            result = await get_collections_fn()

            assert result["total_collections"] == 2
            assert len(result["collections"]) == 2
            assert result["collections"][0]["name"] == "rag_gateway"
            assert result["collections"][0]["document_count"] == 100
            assert result["collections"][1]["name"] == "legal_docs"
            assert result["collections"][1]["document_count"] == 50
            assert "150 total documents" in result["message"]

    @pytest.mark.asyncio
    async def test_list_handles_stats_failure_gracefully(self):
        """Stats failure for one collection shouldn't fail entire list."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list, \
             patch("src.tools.get_collections.get_collection_stats") as mock_stats:

            mock_list.return_value = ["working", "broken"]
            mock_stats.side_effect = [
                {"document_count": 100},
                Exception("Stats failed"),
            ]

            result = await get_collections_fn()

            # Should still return both collections
            assert result["total_collections"] == 2
            assert result["collections"][0]["document_count"] == 100
            assert result["collections"][1]["document_count"] == 0  # Fallback


class TestStatsMode:
    """Tests for getting specific collection stats."""

    @pytest.mark.asyncio
    async def test_get_specific_collection_stats(self):
        """Specific collection should return detailed stats."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list, \
             patch("src.tools.get_collections.get_collection_stats") as mock_stats:

            mock_list.return_value = ["legal_docs", "other"]
            mock_stats.return_value = {
                "document_count": 328,
                "files": ["contract_v1.pdf", "terms.docx"],
            }

            result = await get_collections_fn(collection="legal_docs")

            assert result["name"] == "legal_docs"
            assert result["document_count"] == 328
            assert result["file_count"] == 2
            assert "contract_v1.pdf" in result["files"]

    @pytest.mark.asyncio
    async def test_collection_not_found(self):
        """Non-existent collection should produce helpful error."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list:
            mock_list.return_value = ["rag_gateway", "legal_docs"]

            with pytest.raises(ToolError) as exc:
                await get_collections_fn(collection="unknown")

            assert "not found" in str(exc.value)
            assert "Available collections" in str(exc.value)
            assert "rag_gateway" in str(exc.value)


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_vector_gateway_unavailable(self):
        """Connection errors should have helpful message."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list:
            mock_list.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(ToolError) as exc:
                await get_collections_fn()

            assert "Cannot connect to vector gateway" in str(exc.value)
            assert "VECTOR_GATEWAY_URL" in str(exc.value)

    @pytest.mark.asyncio
    async def test_vector_gateway_not_configured(self):
        """Missing config should produce helpful message."""
        with patch("src.tools.get_collections.service_list_collections") as mock_list:
            mock_list.side_effect = ValueError("VECTOR_GATEWAY_URL not configured")

            with pytest.raises(ToolError) as exc:
                await get_collections_fn()

            assert "VECTOR_GATEWAY_URL" in str(exc.value)

    @pytest.mark.asyncio
    async def test_http_error_in_stats_mode(self):
        """HTTP errors when fetching stats should be handled."""
        mock_response = AsyncMock()
        mock_response.status_code = 500

        with patch("src.tools.get_collections.service_list_collections") as mock_list, \
             patch("src.tools.get_collections.get_collection_stats") as mock_stats:

            mock_list.return_value = ["test"]
            mock_stats.side_effect = httpx.HTTPStatusError(
                "Server error", request=AsyncMock(), response=mock_response
            )

            with pytest.raises(ToolError) as exc:
                await get_collections_fn(collection="test")

            assert "500" in str(exc.value)
