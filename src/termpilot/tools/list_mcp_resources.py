"""MCP 资源列表工具。

对应 TS: tools/ListMcpResourcesTool/ListMcpResourcesTool.ts
列出所有已连接 MCP server 的资源。
"""

from __future__ import annotations

from typing import Any


class ListMcpResourcesTool:
    """列出所有 MCP 资源。"""

    def __init__(self, manager: Any = None) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "list_mcp_resources"

    @property
    def description(self) -> str:
        return (
            "List available resources from all connected MCP servers. "
            "Resources are data sources that MCP servers expose, such as files, APIs, or databases."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Optional server name to filter resources. If omitted, lists all servers.",
                },
            },
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        if not self._manager:
            return "No MCP servers configured."

        server_filter = kwargs.get("server")
        resources = self._manager.get_resources()

        if not resources:
            return "No MCP resources available."

        # 过滤
        if server_filter:
            resources = [r for r in resources if r["server_name"] == server_filter]

        if not resources:
            return f"No resources found for server '{server_filter}'."

        lines = ["MCP Resources:", ""]
        for res in resources:
            server = res["server_name"]
            uri = res.get("uri", "?")
            name = res.get("name", "")
            desc = res.get("description", "")
            line = f"  [{server}] {uri}"
            if name:
                line += f" — {name}"
            if desc:
                line += f"\n    {desc}"
            lines.append(line)

        return "\n".join(lines)
