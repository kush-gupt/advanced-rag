"""Tests for ingest_document tool."""

import os
import tempfile
from unittest.mock import patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from src.tools.ingest_document import ingest_document

# Access underlying function
ingest_document_fn = ingest_document.fn


class TestValidation:
    """Input validation tests."""

    @pytest.mark.asyncio
    async def test_relative_path_rejected(self):
        """Relative paths should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_document_fn(file_path="relative/path.pdf")
        assert "Path must be absolute" in str(exc.value)

    @pytest.mark.asyncio
    async def test_nonexistent_file_rejected(self):
        """Non-existent files should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_document_fn(file_path="/nonexistent/file.pdf")
        assert "File not found" in str(exc.value)
        assert "ingest_from_url" in str(exc.value)

    @pytest.mark.asyncio
    async def test_unsupported_extension_rejected(self):
        """Unsupported file types should be rejected."""
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"test content")
            temp_path = f.name

        try:
            with pytest.raises(ToolError) as exc:
                await ingest_document_fn(file_path=temp_path)
            assert "Unsupported file type" in str(exc.value)
            assert ".pdf" in str(exc.value)
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_insufficient_text_rejected(self):
        """Files with too little text should be rejected."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Short")
            temp_path = f.name

        try:
            with pytest.raises(ToolError) as exc:
                await ingest_document_fn(file_path=temp_path)
            assert "insufficient text" in str(exc.value).lower()
        finally:
            os.unlink(temp_path)


class TestIntegration:
    """Integration tests with mocked services."""

    @pytest.mark.asyncio
    async def test_txt_file_skips_parsing(self):
        """Plain text files should skip Docling parsing."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"This is test content that is long enough for validation. " * 5)
            temp_path = f.name

        try:
            with patch("src.tools.ingest_document.chunk_text") as mock_chunk, \
                 patch("src.tools.ingest_document.upsert_documents") as mock_upsert, \
                 patch("src.tools.ingest_document.parse_document") as mock_parse:

                mock_chunk.return_value = [{"text": "chunk1"}, {"text": "chunk2"}]
                mock_upsert.return_value = {"inserted": 2}

                result = await ingest_document_fn(file_path=temp_path)

                mock_parse.assert_not_called()
                mock_chunk.assert_called_once()
                assert result["success"] is True
                assert result["chunks_created"] == 2
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_pdf_uses_parsing(self):
        """PDF files should use Docling parsing."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            with patch("src.tools.ingest_document.chunk_text") as mock_chunk, \
                 patch("src.tools.ingest_document.upsert_documents") as mock_upsert, \
                 patch("src.tools.ingest_document.parse_document") as mock_parse:

                mock_parse.return_value = "Extracted text from PDF. " * 20
                mock_chunk.return_value = [{"text": "chunk1"}]
                mock_upsert.return_value = {"inserted": 1}

                result = await ingest_document_fn(file_path=temp_path)

                mock_parse.assert_called_once()
                assert result["success"] is True
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_detailed_response_includes_stats(self):
        """Detailed response should include timing stats."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test content for detailed response format testing. " * 10)
            temp_path = f.name

        try:
            with patch("src.tools.ingest_document.chunk_text") as mock_chunk, \
                 patch("src.tools.ingest_document.upsert_documents") as mock_upsert:

                mock_chunk.return_value = [{"text": "chunk1"}]
                mock_upsert.return_value = {"inserted": 1}

                result = await ingest_document_fn(
                    file_path=temp_path,
                    response_format="detailed"
                )

                assert "processing_time_ms" in result
                assert "stages" in result
                assert "estimated_tokens" in result
        finally:
            os.unlink(temp_path)


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_chunker_unavailable(self):
        """Chunker service errors should have helpful message."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test content long enough for processing validation. " * 5)
            temp_path = f.name

        try:
            with patch("src.tools.ingest_document.chunk_text") as mock_chunk:
                mock_chunk.side_effect = httpx.ConnectError("Connection refused")

                with pytest.raises(ToolError) as exc:
                    await ingest_document_fn(file_path=temp_path)

                assert "Cannot connect to chunker service" in str(exc.value)
                assert "CHUNKER_SERVICE_URL" in str(exc.value)
        finally:
            os.unlink(temp_path)
