"""工具注册。

对应 TS: tools.ts (getAllBaseTools, getTools)
"""

from __future__ import annotations

from cc_python.tools.base import Tool, tool_to_api_schema


def get_all_tools() -> list[Tool]:
    """获取所有可用工具。

    对应 TS tools.ts:193 getAllBaseTools()。
    TS 版包含 60+ 工具，Python 版从基础 6 个开始。
    """
    from cc_python.tools.read_file import ReadFileTool
    from cc_python.tools.write_file import WriteFileTool
    from cc_python.tools.edit_file import EditFileTool
    from cc_python.tools.bash import BashTool
    from cc_python.tools.glob_tool import GlobTool
    from cc_python.tools.grep_tool import GrepTool

    return [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ]


def get_tools_api_schemas(tools: list[Tool]) -> list[dict]:
    """生成 Anthropic API 的 tools 参数。

    对应 TS 中将 Tool[] 转换为 API 请求中的 tools 字段。
    """
    return [tool_to_api_schema(t) for t in tools]


def find_tool_by_name(tools: list[Tool], name: str) -> Tool | None:
    """按名称查找工具。对应 TS Tool.ts:358 findToolByName。"""
    for tool in tools:
        if tool.name == name:
            return tool
    return None
