"""MCP 资源读取工具。

对应 TS: tools/ReadMcpResourceTool/ReadMcpResourceTool.ts
读取指定 MCP server 的资源内容。
"""

from __future__ import annotations

from typing import Any


class ReadMcpResourceTool:
    """读取 MCP 资源内容。"""

    def __init__(self, manager: Any = None) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "read_mcp_resource"

    @property
    def description(self) -> str:
        return (
            "Read a specific resource from a connected MCP server. "
            "Use list_mcp_resources first to discover available resources."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "The MCP server name.",
                },
                "uri": {
                    "type": "string",
                    "description": "The resource URI to read.",
                },
            },
            "required": ["server", "uri"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        if not self._manager:
            return "No MCP servers configured."

        server = kwargs.get("server", "")
        uri = kwargs.get("uri", "")

        if not server or not uri:
            return "Error: Both 'server' and 'uri' are required."

        return await self._manager.read_resource(server, uri)
