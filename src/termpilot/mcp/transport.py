"""MCP 传输层。

对应 TS: @modelcontextprotocol/sdk/client/stdio.js + sse.js
Python 简化版仅实现 stdio 和 sse 两种传输。

JSON-RPC 2.0 消息通过 transport 发送/接收。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# JSON-RPC 消息结束标记（MCP stdio 协议规定用空行分隔）
_MESSAGE_DELIMITER = "\n"


class BaseTransport(ABC):
    """传输层基类。"""

    @abstractmethod
    async def start(self) -> None:
        """建立连接。"""
        ...

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """发送 JSON-RPC 消息。"""
        ...

    @abstractmethod
    async def receive(self) -> dict[str, Any]:
        """接收一条 JSON-RPC 响应。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭连接。"""
        ...


class StdioTransport(BaseTransport):
    """stdio 传输：通过子进程的 stdin/stdout 进行 JSON-RPC 通信。

    对应 TS: StdioClientTransport
    启动 MCP server 子进程，通过 stdin 发送请求，从 stdout 读取响应。
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._reader_lock = asyncio.Lock()

    async def start(self) -> None:
        """启动子进程。"""
        env = dict(os.environ)
        if self._env:
            env.update(self._env)

        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        logger.debug(
            "StdioTransport started: %s %s (pid=%s)",
            self._command, " ".join(self._args), self._process.pid,
        )

    async def send(self, message: dict[str, Any]) -> None:
        """向子进程 stdin 写入 JSON-RPC 消息。"""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Transport not started")
        data = json.dumps(message) + _MESSAGE_DELIMITER
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        """从子进程 stdout 读取一行 JSON-RPC 响应。"""
        if not self._process or not self._process.stdout:
            raise RuntimeError("Transport not started")

        async with self._reader_lock:
            line = await self._process.stdout.readline()

        if not line:
            raise RuntimeError("MCP server closed connection")

        text = line.decode("utf-8").strip()
        if not text:
            raise RuntimeError("Empty response from MCP server")

        return json.loads(text)

    async def close(self) -> None:
        """终止子进程。"""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None


class SSETransport(BaseTransport):
    """SSE 传输：通过 HTTP SSE 连接进行 JSON-RPC 通信。

    对应 TS: SSEClientTransport
    发送请求通过 POST，接收响应通过 SSE 事件流。
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._headers = headers or {}
        self._message_endpoint: str | None = None
        self._response_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._session: Any = None
        self._sse_task: asyncio.Task | None = None

    async def start(self) -> None:
        """建立 SSE 连接。"""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx is required for SSE MCP transport. Install with: pip install httpx")

        self._session = httpx.AsyncClient(timeout=30.0)

        # 连接 SSE 端点，获取 message endpoint
        headers = {**self._headers, "Accept": "text/event-stream"}
        response = await self._session.get(
            f"{self._url}/sse",
            headers=headers,
        )
        response.raise_for_status()

        # 解析 SSE 事件找到 endpoint
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:].strip()
                if data.startswith("/"):
                    self._message_endpoint = f"{self._url}{data}"
                else:
                    self._message_endpoint = data
                break

        if not self._message_endpoint:
            # 简化：假设 message endpoint 就是 /message
            self._message_endpoint = f"{self._url}/message"

        logger.debug("SSETransport connected: %s → %s", self._url, self._message_endpoint)

    async def send(self, message: dict[str, Any]) -> None:
        """通过 POST 发送 JSON-RPC 消息。"""
        if not self._session or not self._message_endpoint:
            raise RuntimeError("Transport not started")

        response = await self._session.post(
            self._message_endpoint,
            json=message,
            headers={**self._headers, "Content-Type": "application/json"},
        )
        response.raise_for_status()

        # SSE 模式下，响应可能直接在 POST 返回中
        try:
            data = response.json()
            if "id" in data or "result" in data or "error" in data:
                await self._response_queue.put(data)
        except (json.JSONDecodeError, ValueError):
            pass

    async def receive(self) -> dict[str, Any]:
        """从响应队列中获取响应。"""
        try:
            return await asyncio.wait_for(self._response_queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            raise RuntimeError("Timeout waiting for MCP response")

    async def close(self) -> None:
        """关闭 SSE 连接。"""
        if self._sse_task:
            self._sse_task.cancel()
            self._sse_task = None
        if self._session:
            await self._session.aclose()
            self._session = None
