"""WebFetch 工具 — 抓取网页内容并转为 Markdown。

对应 TS: tools/WebFetchTool/ (~9K 行)
Python 简化版：URL 校验 + SSRF 防护 + TTL 缓存 + HTML→Markdown。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
FETCH_TIMEOUT = 60.0          # HTTP 请求超时（秒）
MAX_CONTENT_SIZE = 10 * 1024 * 1024  # 最大响应体 10MB
MAX_OUTPUT_CHARS = 50_000     # 输出截断字符数
CACHE_TTL = 900               # 缓存 15 分钟
MAX_CACHE_ENTRIES = 50        # 最大缓存条目
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 需要在 HTML→Markdown 前移除的标签
STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript"}


# ---------------------------------------------------------------------------
# URL 校验 + SSRF 防护
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> str:
    """校验 URL 合法性和安全性。

    - scheme 必须是 http 或 https
    - 必须有 hostname
    - DNS 解析后拒绝私有/保留 IP
    """
    if not url or not url.strip():
        raise ValueError("URL is empty")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r} (only http/https)")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # 直接检查 hostname 是否是 IP 字面量
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # 不是 IP 字面量，走 DNS 解析
    else:
        if _is_restricted_ip(ip):
            raise ValueError(f"URL points to a private/restricted IP: {hostname}")
        return url

    # DNS 解析后检查
    _check_dns_not_private(hostname)
    return url


def _is_restricted_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否为私有/保留/回环地址。"""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _check_dns_not_private(hostname: str) -> None:
    """解析 DNS 并验证目标 IP 不是私有地址。"""
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from e

    for family, _type, _proto, _canon, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if _is_restricted_ip(ip):
                raise ValueError(f"Hostname {hostname} resolves to private IP: {ip_str}")
        except ValueError:
            continue  # skip non-IP results


# ---------------------------------------------------------------------------
# 简易 TTL 缓存
# ---------------------------------------------------------------------------

class _WebFetchCache:
    """实例级 TTL 缓存，不依赖外部库。"""

    def __init__(self, ttl: int = CACHE_TTL, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, url: str) -> str | None:
        entry = self._store.get(url)
        if entry is None:
            return None
        expiry, content = entry
        if time.monotonic() >= expiry:
            del self._store[url]
            return None
        return content

    def put(self, url: str, content: str) -> None:
        # 淘汰过期条目
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]

        # 容量限制：淘汰最早的
        while len(self._store) >= self._max:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]

        self._store[url] = (now + self._ttl, content)

    def clear(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def _html_to_markdown(html: str, url: str) -> str:
    """将 HTML 转为 Markdown 文本。

    1. 用 BeautifulSoup 移除干扰标签
    2. 用 markdownify 转换
    3. 清理多余空行
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify as md

    soup = BeautifulSoup(html, "html.parser")

    # 移除干扰标签
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()

    # 转换
    text = md(str(soup), heading_style="ATX", strip=["img"])

    # 清理多余空行（超过 2 个连续换行 → 2 个）
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 添加来源信息
    text = f"(Fetched from: {url})\n\n{text}"
    return text.strip()


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------

class WebFetchTool:
    """抓取网页内容并转为 Markdown。

    对应 TS: tools/WebFetchTool/。
    只读工具，is_concurrency_safe=True。
    """

    def __init__(self) -> None:
        self._cache = _WebFetchCache()

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch and convert a web page URL to markdown text. "
            "Use this tool when you need to read the contents of a web page, "
            "documentation, or any URL. The HTML content is automatically "
            "converted to clean markdown for easy reading.\n"
            "\n"
            "IMPORTANT: This tool is for reading web content only. "
            "Do NOT generate or guess URLs unless you are confident they are real. "
            "Only use URLs provided by the user or found in search results."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from. Must be a valid http:// or https:// URL.",
                },
                "raw": {
                    "type": "boolean",
                    "description": "If true, return raw HTML instead of Markdown conversion. Default false.",
                },
            },
            "required": ["url"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        raw = kwargs.get("raw", False)

        if not url or not url.strip():
            return "Error: URL is required."

        # 1. URL 校验
        try:
            url = _validate_url(url)
        except ValueError as e:
            return f"Error: {e}"

        # 2. 查缓存
        cached = self._cache.get(url)
        if cached is not None:
            logger.debug("web_fetch cache hit: %s", url)
            return cached

        # 3. HTTP 请求
        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT,
                follow_redirects=True,
                max_redirects=5,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(url)

        except httpx.TimeoutException:
            return f"Error: Request timed out after {FETCH_TIMEOUT}s: {url}"
        except httpx.TooManyRedirects:
            return f"Error: Too many redirects: {url}"
        except httpx.RequestError as e:
            return f"Error: Request failed: {e}"

        if response.status_code != 200:
            return f"Error: HTTP {response.status_code} for {url}"

        # 4. 大小检查
        content_length = len(response.content)
        if content_length > MAX_CONTENT_SIZE:
            return f"Error: Response too large ({content_length:,} bytes, max {MAX_CONTENT_SIZE:,})"

        # 5. 非 HTML 或 raw 模式 → 直接返回
        content_type = response.headers.get("content-type", "")
        is_html = "text/html" in content_type or "application/xhtml" in content_type

        if raw or not is_html:
            text = response.text
            if len(text) > MAX_OUTPUT_CHARS:
                text = text[:MAX_OUTPUT_CHARS] + f"\n\n[... truncated at {MAX_OUTPUT_CHARS} chars]"
            self._cache.put(url, text)
            return text

        # 6. HTML → Markdown
        try:
            text = _html_to_markdown(response.text, url)
        except Exception as e:
            logger.warning("HTML→Markdown conversion failed: %s, returning raw text", e)
            text = response.text

        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + f"\n\n[... truncated at {MAX_OUTPUT_CHARS} chars]"

        self._cache.put(url, text)
        logger.debug("web_fetch: %s → %d chars", url, len(text))
        return text
