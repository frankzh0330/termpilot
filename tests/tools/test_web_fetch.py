"""WebFetch 工具测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cc_python.tools.web_fetch import (
    WebFetchTool,
    _validate_url,
    _WebFetchCache,
    _html_to_markdown,
)


@pytest.fixture
def tool() -> WebFetchTool:
    return WebFetchTool()


class TestWebFetchToolProtocol:
    def test_name(self, tool: WebFetchTool) -> None:
        assert tool.name == "web_fetch"

    def test_is_concurrency_safe(self, tool: WebFetchTool) -> None:
        assert tool.is_concurrency_safe is True

    def test_has_schema(self, tool: WebFetchTool) -> None:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "url" in schema["properties"]
        assert "url" in schema["required"]


class TestWebFetchValidation:
    def test_invalid_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("ftp://example.com")

    def test_no_hostname(self) -> None:
        with pytest.raises(ValueError, match="no hostname"):
            _validate_url("http://")

    def test_localhost_rejected(self) -> None:
        with pytest.raises(ValueError, match="private"):
            _validate_url("http://127.0.0.1:8080/api")

    def test_private_ip_rejected(self) -> None:
        with pytest.raises(ValueError, match="private"):
            _validate_url("http://192.168.1.1/admin")

    def test_valid_url_passes(self) -> None:
        url = _validate_url("https://example.com")
        assert url == "https://example.com"


class TestWebFetchCache:
    def test_cache_put_and_get(self) -> None:
        cache = _WebFetchCache(ttl=60)
        cache.put("https://example.com", "content")
        assert cache.get("https://example.com") == "content"

    def test_cache_miss(self) -> None:
        cache = _WebFetchCache()
        assert cache.get("https://nonexistent.com") is None

    def test_cache_clear(self) -> None:
        cache = _WebFetchCache()
        cache.put("https://example.com", "content")
        cache.clear()
        assert cache.get("https://example.com") is None


class TestWebFetchCall:
    @pytest.mark.asyncio
    async def test_fetch_error_empty_url(self, tool: WebFetchTool) -> None:
        result = await tool.call(url="")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_fetch_private_ip(self, tool: WebFetchTool) -> None:
        result = await tool.call(url="http://127.0.0.1/secret")
        assert "Error" in result
        assert "private" in result.lower()

    @pytest.mark.asyncio
    async def test_fetch_success_html(self, tool: WebFetchTool) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.text = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        mock_response.content = mock_response.text.encode()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as _httpx
        with patch.object(_httpx, "AsyncClient", return_value=mock_client):
            with patch("cc_python.tools.web_fetch._validate_url", return_value="https://example.com"):
                result = await tool.call(url="https://example.com")

        assert "Hello" in result
        assert "World" in result

    @pytest.mark.asyncio
    async def test_fetch_non_html_passthrough(self, tool: WebFetchTool) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"key": "value"}'
        mock_response.content = mock_response.text.encode()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as _httpx
        with patch.object(_httpx, "AsyncClient", return_value=mock_client):
            with patch("cc_python.tools.web_fetch._validate_url", return_value="https://api.example.com/data"):
                result = await tool.call(url="https://api.example.com/data")

        assert '{"key": "value"}' in result

    @pytest.mark.asyncio
    async def test_fetch_http_error(self, tool: WebFetchTool) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_response.content = b""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as _httpx
        with patch.object(_httpx, "AsyncClient", return_value=mock_client):
            with patch("cc_python.tools.web_fetch._validate_url", return_value="https://example.com/missing"):
                result = await tool.call(url="https://example.com/missing")

        assert "Error" in result
        assert "404" in result


class TestHtmlToMarkdown:
    def test_basic_conversion(self) -> None:
        html = "<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        result = _html_to_markdown(html, "https://example.com")
        assert "Title" in result
        assert "Paragraph" in result
        assert "example.com" in result

    def test_script_tags_removed(self) -> None:
        html = "<html><body><script>alert('xss')</script><p>Content</p></body></html>"
        result = _html_to_markdown(html, "https://example.com")
        assert "alert" not in result
        assert "Content" in result
