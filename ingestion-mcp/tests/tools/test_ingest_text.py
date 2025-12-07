"""Tests for ingest_text tool."""

from unittest.mock import patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from src.tools.ingest_text import ingest_text

# Access the underlying function for testing (FastMCP decorator pattern)
ingest_text_fn = ingest_text.fn


class TestValidation:
    """Input validation tests."""

    @pytest.mark.asyncio
    async def test_empty_text_rejected(self):
        """Empty text should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_text_fn(text="")
        assert "cannot be empty" in str(exc.value)

    @pytest.mark.asyncio
    async def test_whitespace_only_rejected(self):
        """Whitespace-only text should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_text_fn(text="   \n\t   ")
        assert "cannot be empty" in str(exc.value)

    @pytest.mark.asyncio
    async def test_short_text_rejected(self):
        """Text shorter than 50 characters should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_text_fn(text="Short text")
        assert "too short" in str(exc.value)
        assert "50 characters" in str(exc.value)

    @pytest.mark.asyncio
    async def test_minimum_length_text_accepted(self):
        """Text with exactly 50 characters should be accepted."""
        # 50 characters of meaningful content
        text = "A" * 50

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_text_fn(text=text)

            assert result["success"] is True


class TestIntegration:
    """Integration tests with mocked services."""

    @pytest.mark.asyncio
    async def test_basic_ingestion(self):
        """Basic text ingestion should succeed."""
        text = "This is sample text content for testing the ingestion pipeline. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}, {"text": "chunk2"}]
            mock_upsert.return_value = {"inserted": 2}

            result = await ingest_text_fn(text=text)

            mock_chunk.assert_called_once()
            mock_upsert.assert_called_once()
            assert result["success"] is True
            assert result["chunks_created"] == 2

    @pytest.mark.asyncio
    async def test_custom_name_and_source(self):
        """Custom name and source should be included in metadata."""
        text = "Test content that is long enough for validation and processing. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_text_fn(
                text=text,
                name="meeting-notes",
                source="api-upload"
            )

            assert result["name"] == "meeting-notes"

            # Verify metadata was passed correctly
            call_args = mock_upsert.call_args[0][0]
            assert call_args[0]["metadata"]["name"] == "meeting-notes"
            assert call_args[0]["metadata"]["source"] == "api-upload"

    @pytest.mark.asyncio
    async def test_tags_included_in_metadata(self):
        """Tags should be included in chunk metadata."""
        text = "Test content for tag verification and testing purposes. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            await ingest_text_fn(
                text=text,
                tags=["important", "meeting"]
            )

            call_args = mock_upsert.call_args[0][0]
            assert call_args[0]["metadata"]["tags"] == ["important", "meeting"]

    @pytest.mark.asyncio
    async def test_detailed_response_includes_stats(self):
        """Detailed response should include timing stats."""
        text = "Test content for detailed response format testing purposes. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_text_fn(
                text=text,
                response_format="detailed"
            )

            assert "processing_time_ms" in result
            assert "stages" in result
            assert "estimated_tokens" in result
            assert "text_length" in result


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_chunker_unavailable(self):
        """Chunker service errors should have helpful message."""
        text = "Test content long enough for processing validation. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk:
            mock_chunk.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(ToolError) as exc:
                await ingest_text_fn(text=text)

            assert "Cannot connect to chunker service" in str(exc.value)
            assert "CHUNKER_SERVICE_URL" in str(exc.value)

    @pytest.mark.asyncio
    async def test_vector_gateway_unavailable(self):
        """Vector gateway errors should have helpful message."""
        text = "Test content long enough for processing validation. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_text.upsert_documents") as mock_upsert:

            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(ToolError) as exc:
                await ingest_text_fn(text=text)

            assert "Cannot connect to vector gateway" in str(exc.value)
            assert "VECTOR_GATEWAY_URL" in str(exc.value)

    @pytest.mark.asyncio
    async def test_empty_chunks_error(self):
        """Empty chunk result should produce helpful error."""
        text = "Test content long enough for processing validation. " * 3

        with patch("src.tools.ingest_text.chunk_text") as mock_chunk:
            mock_chunk.return_value = []

            with pytest.raises(ToolError) as exc:
                await ingest_text_fn(text=text)

            assert "no chunks" in str(exc.value)
            assert "dense" in str(exc.value)  # Should suggest dense chunking
