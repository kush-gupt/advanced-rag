"""Tests for ingest_from_url tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from src.tools.ingest_from_url import ingest_from_url, extract_text_from_html

# Access the underlying function for testing (FastMCP decorator pattern)
ingest_from_url_fn = ingest_from_url.fn


class TestValidation:
    """Input validation tests."""

    @pytest.mark.asyncio
    async def test_empty_url_rejected(self):
        """Empty URL should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_from_url_fn(url="")
        assert "cannot be empty" in str(exc.value)

    @pytest.mark.asyncio
    async def test_invalid_scheme_rejected(self):
        """Non-HTTP schemes should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_from_url_fn(url="ftp://example.com/file.pdf")
        assert "Invalid URL scheme" in str(exc.value)
        assert "HTTP" in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_domain_rejected(self):
        """URLs without domain should be rejected."""
        with pytest.raises(ToolError) as exc:
            await ingest_from_url_fn(url="http:///path/file.pdf")
        assert "Invalid URL" in str(exc.value)


class TestHtmlExtraction:
    """Tests for HTML text extraction helper."""

    def test_removes_scripts(self):
        """Script tags should be removed."""
        html = "<p>Hello</p><script>alert('x')</script><p>World</p>"
        result = extract_text_from_html(html)
        assert "alert" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_styles(self):
        """Style tags should be removed."""
        html = "<p>Hello</p><style>.cls{color:red}</style><p>World</p>"
        result = extract_text_from_html(html)
        assert "color" not in result
        assert "Hello" in result

    def test_decodes_entities(self):
        """HTML entities should be decoded."""
        html = "<p>Fish &amp; Chips &lt;3</p>"
        result = extract_text_from_html(html)
        assert "Fish & Chips <3" in result


class TestIntegration:
    """Integration tests with mocked services."""

    @pytest.mark.asyncio
    async def test_plain_text_url(self):
        """Plain text URL should be processed directly."""
        mock_response = MagicMock()
        mock_response.content = b"This is plain text content that is long enough for chunking. " * 3
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_chunk.return_value = [{"text": "chunk1"}, {"text": "chunk2"}]
            mock_upsert.return_value = {"inserted": 2}

            result = await ingest_from_url_fn(url="https://example.com/file.txt")

            assert result["success"] is True
            assert result["content_type"] == "TXT"
            assert result["chunks_created"] == 2

    @pytest.mark.asyncio
    async def test_html_url(self):
        """HTML URL should have text extracted."""
        html_content = b"<html><body><p>This is HTML content that is long enough for testing. " * 3 + b"</p></body></html>"
        mock_response = MagicMock()
        mock_response.content = html_content
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_from_url_fn(url="https://example.com/page.html")

            assert result["success"] is True
            assert result["content_type"] == "HTML"

    @pytest.mark.asyncio
    async def test_pdf_url_uses_docling(self):
        """PDF URL should use Docling for parsing."""
        mock_response = MagicMock()
        mock_response.content = b"%PDF-1.4 test content"
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.parse_document") as mock_parse, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_parse.return_value = "Extracted PDF text that is long enough. " * 5
            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_from_url_fn(url="https://example.com/doc.pdf")

            mock_parse.assert_called_once()
            assert result["content_type"] == "PDF"

    @pytest.mark.asyncio
    async def test_infers_type_from_url_extension(self):
        """Content type should be inferred from URL extension if header missing."""
        mock_response = MagicMock()
        mock_response.content = b"This is plain text content that is long enough for chunking. " * 3
        mock_response.headers = {"content-type": "application/octet-stream"}  # Generic
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_from_url_fn(url="https://example.com/readme.txt")

            assert result["content_type"] == "TXT"

    @pytest.mark.asyncio
    async def test_source_defaults_to_domain(self):
        """Source should default to URL domain."""
        mock_response = MagicMock()
        mock_response.content = b"This is plain text content that is long enough for chunking. " * 3
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            await ingest_from_url_fn(url="https://docs.example.com/guide.txt")

            call_args = mock_upsert.call_args[0][0]
            assert call_args[0]["metadata"]["source"] == "docs.example.com"

    @pytest.mark.asyncio
    async def test_detailed_response_includes_stats(self):
        """Detailed response should include timing stats."""
        mock_response = MagicMock()
        mock_response.content = b"This is plain text content that is long enough for chunking. " * 3
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client, \
             patch("src.tools.ingest_from_url.chunk_text") as mock_chunk, \
             patch("src.tools.ingest_from_url.upsert_documents") as mock_upsert:

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_chunk.return_value = [{"text": "chunk1"}]
            mock_upsert.return_value = {"inserted": 1}

            result = await ingest_from_url_fn(
                url="https://example.com/file.txt",
                response_format="detailed"
            )

            assert "processing_time_ms" in result
            assert "stages" in result
            assert "fetch_ms" in result["stages"]
            assert "content_length" in result


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_404_error(self):
        """404 error should have helpful message."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Not Found", request=MagicMock(), response=mock_response
                )
            )

            with pytest.raises(ToolError) as exc:
                await ingest_from_url_fn(url="https://example.com/missing.pdf")

            assert "404" in str(exc.value)
            assert "publicly accessible" in str(exc.value)

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Connection errors should have helpful message."""
        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            with pytest.raises(ToolError) as exc:
                await ingest_from_url_fn(url="https://unreachable.example.com/doc.pdf")

            assert "Cannot connect" in str(exc.value)

    @pytest.mark.asyncio
    async def test_unsupported_content_type(self):
        """Unsupported content types should produce helpful error."""
        mock_response = MagicMock()
        mock_response.content = b"binary data"
        mock_response.headers = {"content-type": "application/zip"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ToolError) as exc:
                await ingest_from_url_fn(url="https://example.com/archive")

            assert "Unsupported content type" in str(exc.value)

    @pytest.mark.asyncio
    async def test_insufficient_text(self):
        """Short content should produce helpful error."""
        mock_response = MagicMock()
        mock_response.content = b"Short"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.tools.ingest_from_url.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ToolError) as exc:
                await ingest_from_url_fn(url="https://example.com/short.txt")

            assert "insufficient text" in str(exc.value)
