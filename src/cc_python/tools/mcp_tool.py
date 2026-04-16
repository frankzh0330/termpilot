"""MCP 工具适配器。

对应 TS: tools/MCPTool/MCPTool.ts
将 MCP server 的工具包装为 Tool 协议，使模型能通过工具调用使用 MCP 工具。

每个 MCP server 的工具被包装为独立的 MCPToolAdapter 实例，
工具名格式：mcp__<serverName>__<toolName>
"""

from __future__ import annotations

from typing import Any


class MCPToolAdapter:
    """MCP 工具适配器，实现 Tool 协议。

    包装 MCP server 的单个工具，使其能被工具调用循环识别和执行。
    """

    def __init__(
            self,
            server_name: str,
            tool_name: str,
            description: str = "",
            input_schema: dict[str, Any] | None = None,
            manager: Any = None,
    ) -> None:
        self._server_name = server_name
        self._tool_name = tool_name
        self._full_name = f"mcp__{server_name}__{tool_name}"
        self._description = description or f"MCP tool: {tool_name} (from {server_name})"
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._manager = manager

    @property
    def name(self) -> str:
        return self._full_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def is_concurrency_safe(self) -> bool:
        return True  # MCP 工具默认安全，可并行执行

    async def call(self, **kwargs: Any) -> str:
        """执行 MCP 工具调用，委托给 MCPManager。"""
        if not self._manager:
            return f"Error: MCP manager not available for tool '{self._full_name}'"

        # 过滤掉不属于工具参数的额外字段
        tool_args = {k: v for k, v in kwargs.items()
                     if k not in ("tool_use_id",)}

        return await self._manager.call_tool(self._full_name, tool_args)


def create_mcp_tools(manager: Any) -> list[MCPToolAdapter]:
    """从 MCPManager 的工具列表创建 MCPToolAdapter 实例。

    Args:
        manager: MCPManager 实例

    Returns:
        MCPToolAdapter 列表
    """
    adapters = []
    for tool_info in manager.get_tools():
        adapter = MCPToolAdapter(
            server_name=tool_info["server_name"],
            tool_name=tool_info["tool_name"],
            description=tool_info.get("description", ""),
            input_schema=tool_info.get("input_schema", {}),
            manager=manager,
        )
        adapters.append(adapter)
    return adapters
