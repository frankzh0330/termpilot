"""WebSearch 工具 — 网页搜索。

对应 TS: tools/WebSearchTool/ (~13K 行)
Python 简化版：DuckDuckGo 搜索 + 域名过滤，无需 API key。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
MAX_RESULTS_DEFAULT = 10
MAX_RESULTS_CAP = 20
MAX_QUERY_LENGTH = 500
MAX_OUTPUT_CHARS = 30_000


# ---------------------------------------------------------------------------
# 域名过滤
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """从 URL 提取域名（小写）。"""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def _apply_domain_filters(
    results: list[dict[str, str]],
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
) -> list[dict[str, str]]:
    """按白名单/黑名单过滤搜索结果。"""
    if not allowed_domains and not blocked_domains:
        return results

    allowed_set = {d.lower() for d in allowed_domains} if allowed_domains else None
    blocked_set = {d.lower() for d in blocked_domains} if blocked_domains else None

    filtered = []
    for r in results:
        domain = _extract_domain(r.get("href", "") or r.get("url", ""))

        if blocked_set and domain in blocked_set:
            continue
        if allowed_set and domain not in allowed_set:
            continue

        filtered.append(r)

    return filtered


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

class WebSearchTool:
    """网页搜索工具。

    对应 TS: tools/WebSearchTool/。
    使用 DuckDuckGo 搜索，无需 API key。
    只读工具，is_concurrency_safe=True。
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using a search engine. Returns a list of results "
            "with titles, URLs, and snippets.\n"
            "\n"
            "Use this tool when you need up-to-date information, recent data, "
            "or to find specific web pages. Always include source URLs in your "
            "response when citing search results.\n"
            "\n"
            "IMPORTANT: Do NOT use this tool for questions about well-established "
            "facts or topics within your training data. Prefer your built-in "
            "knowledge for such queries."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"Maximum number of results to return. Default {MAX_RESULTS_DEFAULT}, max {MAX_RESULTS_CAP}.",
                },
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only include results from these domains. Optional.",
                },
                "blocked_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains. Optional.",
                },
            },
            "required": ["query"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", MAX_RESULTS_DEFAULT)
        allowed_domains = kwargs.get("allowed_domains")
        blocked_domains = kwargs.get("blocked_domains")

        # 1. 参数校验
        if not query or not query.strip():
            return "Error: Search query is required."

        if len(query) > MAX_QUERY_LENGTH:
            return f"Error: Query too long ({len(query)} chars, max {MAX_QUERY_LENGTH})."

        # 2. 钳制结果数
        max_results = max(1, min(int(max_results), MAX_RESULTS_CAP))

        # 如果有域名过滤，多取一些再过滤
        fetch_count = max_results * 3 if (allowed_domains or blocked_domains) else max_results

        # 3. 执行搜索
        try:
            import asyncio
            from duckduckgo_search import DDGS

            ddgs = DDGS()
            raw_results = await asyncio.to_thread(
                ddgs.text, query, max_results=fetch_count
            )

        except ImportError:
            return "Error: duckduckgo-search is not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            logger.warning("web_search failed: %s", e)
            return f"Error: Search failed: {e}"

        if not raw_results:
            return f"No results found for: {query}"

        # 4. 标准化结果格式
        results: list[dict[str, str]] = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "href": r.get("href", ""),
                "body": r.get("body", ""),
            })

        # 5. 域名过滤
        results = _apply_domain_filters(results, allowed_domains, blocked_domains)

        # 6. 截断到 max_results
        results = results[:max_results]

        if not results:
            return f"No results found after domain filtering for: {query}"

        # 7. 格式化输出
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            title = r["title"] or "Untitled"
            href = r["href"]
            body = r["body"]
            lines.append(f"{i}. [{title}]({href})")
            if body:
                lines.append(f"   {body}")
            lines.append("")

        output = "\n".join(lines)

        # 8. 截断
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n\n[... truncated at {MAX_OUTPUT_CHARS} chars]"

        logger.debug("web_search: %r → %d results (%d chars)", query, len(results), len(output))
        return output
