"""工具基类定义。

对应 TS: Tool.ts (Tool 类型 + buildTool)

TS 中 Tool 是一个包含 30+ 方法的巨型接口（call, description, prompt,
renderToolUseMessage, checkPermissions, isConcurrencySafe 等），
大部分是 UI/权限/渲染相关。

Python 简化版只保留核心：
- name: 工具名称（API 中用于匹配）
- description: 工具描述（传给模型的，决定模型何时调用）
- input_schema: JSON Schema 格式的参数定义
- is_concurrency_safe: 是否可以与其他工具并行执行
- call(input): 执行工具并返回结果文本
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """工具协议。

    对应 TS Tool.ts:362 的 Tool 类型，大幅简化。
    所有工具必须实现此协议。
    """

    @property
    def name(self) -> str:
        """工具名称，如 'read_file'。对应 TS Tool.name。"""
        ...

    @property
    def description(self) -> str:
        """工具描述，传给模型以决定何时调用此工具。对应 TS Tool.description()。"""
        ...

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema 格式的参数定义。

        对应 TS Tool.inputSchema（Zod schema）。
        Anthropic API 要求格式如：
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"}
            },
            "required": ["file_path"]
        }
        """
        ...

    @property
    def is_concurrency_safe(self) -> bool:
        """是否可以与其他工具并行执行。

        对应 TS Tool.ts isConcurrencySafe()。
        只读工具（Read, Glob, Grep）返回 True，
        有副作用的工具（Write, Edit, Bash）返回 False。

        默认 False（fail-closed，和 TS 一致）。
        """
        return False

    async def call(self, **kwargs: Any) -> str:
        """执行工具并返回结果文本。

        对应 TS Tool.call() → ToolResult。
        TS 版返回 ToolResult 对象（含 data, newMessages 等），
        Python 简化版直接返回文本字符串。
        """
        ...


def tool_to_api_schema(tool: Tool) -> dict[str, Any]:
    """将工具转换为 Anthropic API 的 tools 参数格式。

    对应 TS 中 tools 被 serializeToolsForAPI 处理后的格式。

    Anthropic API 要求：
    {
        "name": "read_file",
        "description": "读取文件内容",
        "input_schema": { "type": "object", "properties": {...}, "required": [...] }
    }
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
