"""WebSearch 工具测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cc_python.tools.web_search import (
    WebSearchTool,
    _extract_domain,
    _apply_domain_filters,
)


@pytest.fixture
def tool() -> WebSearchTool:
    return WebSearchTool()


class TestWebSearchToolProtocol:
    def test_name(self, tool: WebSearchTool) -> None:
        assert tool.name == "web_search"

    def test_is_concurrency_safe(self, tool: WebSearchTool) -> None:
        assert tool.is_concurrency_safe is True

    def test_has_schema(self, tool: WebSearchTool) -> None:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "query" in schema["required"]
        assert "allowed_domains" in schema["properties"]
        assert "blocked_domains" in schema["properties"]


class TestExtractDomain:
    def test_basic(self) -> None:
        assert _extract_domain("https://example.com/path") == "example.com"

    def test_subdomain(self) -> None:
        assert _extract_domain("https://docs.python.org/3/") == "docs.python.org"

    def test_empty_url(self) -> None:
        assert _extract_domain("") == ""


class TestDomainFilters:
    @pytest.fixture
    def sample_results(self) -> list[dict[str, str]]:
        return [
            {"title": "Python", "href": "https://python.org", "body": "Python language"},
            {"title": "GitHub", "href": "https://github.com", "body": "Code hosting"},
            {"title": "Stack Overflow", "href": "https://stackoverflow.com/q/1", "body": "Q&A"},
        ]

    def test_no_filters(self, sample_results: list) -> None:
        result = _apply_domain_filters(sample_results, None, None)
        assert len(result) == 3

    def test_allowed_domains(self, sample_results: list) -> None:
        result = _apply_domain_filters(sample_results, ["python.org"], None)
        assert len(result) == 1
        assert result[0]["title"] == "Python"

    def test_blocked_domains(self, sample_results: list) -> None:
        result = _apply_domain_filters(sample_results, None, ["github.com"])
        assert len(result) == 2
        assert all(r["title"] != "GitHub" for r in result)

    def test_case_insensitive(self, sample_results: list) -> None:
        result = _apply_domain_filters(sample_results, ["PYTHON.ORG"], None)
        assert len(result) == 1


class TestWebSearchCall:
    @pytest.mark.asyncio
    async def test_empty_query(self, tool: WebSearchTool) -> None:
        result = await tool.call(query="")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_long_query_rejected(self, tool: WebSearchTool) -> None:
        result = await tool.call(query="x" * 501)
        assert "Error" in result
        assert "too long" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_search(self, tool: WebSearchTool) -> None:
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=[
            {"title": "Result 1", "href": "https://example.com/1", "body": "Body 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Body 2"},
        ])

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs_instance):
            result = await tool.call(query="test query")

        assert "Result 1" in result
        assert "example.com/1" in result
        assert "Body 1" in result

    @pytest.mark.asyncio
    async def test_no_results(self, tool: WebSearchTool) -> None:
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=[])

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs_instance):
            result = await tool.call(query="obscure query xyz123")

        assert "No results" in result

    @pytest.mark.asyncio
    async def test_domain_filtering(self, tool: WebSearchTool) -> None:
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=[
            {"title": "Python", "href": "https://python.org", "body": "Python"},
            {"title": "Ruby", "href": "https://ruby-lang.org", "body": "Ruby"},
        ])

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs_instance):
            result = await tool.call(
                query="programming",
                allowed_domains=["python.org"],
            )

        assert "Python" in result
        assert "Ruby" not in result

    @pytest.mark.asyncio
    async def test_max_results_cap(self, tool: WebSearchTool) -> None:
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=[])

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs_instance):
            await tool.call(query="test", max_results=100)
            # fetch_count 被钳制
            call_args = mock_ddgs_instance.text.call_args
            assert call_args[1]["max_results"] <= 60  # 20 * 3
