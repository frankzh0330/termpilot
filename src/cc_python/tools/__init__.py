"""工具注册。

对应 TS: tools.ts (getAllBaseTools, getTools)
"""

from __future__ import annotations

import logging
from typing import Any

from cc_python.tools.base import Tool, tool_to_api_schema

logger = logging.getLogger(__name__)


def get_all_tools(mcp_manager: Any | None = None) -> list[Tool]:
    """获取所有可用工具。

    对应 TS tools.ts:193 getAllBaseTools()。
    TS 版包含 60+ 工具，Python 版从基础 6 个 + MCP 动态工具 + Skill 工具。
    """
    from cc_python.tools.read_file import ReadFileTool
    from cc_python.tools.write_file import WriteFileTool
    from cc_python.tools.edit_file import EditFileTool
    from cc_python.tools.bash import BashTool
    from cc_python.tools.glob_tool import GlobTool
    from cc_python.tools.grep_tool import GrepTool

    tools: list[Tool] = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ]

    # 高级工具（Phase 8）
    from cc_python.tools.ask_user import AskUserQuestionTool
    from cc_python.tools.agent import AgentTool
    from cc_python.tools.task import (
        TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool,
    )
    from cc_python.tools.enter_plan import EnterPlanModeTool
    from cc_python.tools.exit_plan import ExitPlanModeTool
    from cc_python.tools.notebook_edit import NotebookEditTool

    tools.extend([
        AskUserQuestionTool(),
        AgentTool(),
        TaskCreateTool(),
        TaskUpdateTool(),
        TaskListTool(),
        TaskGetTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        NotebookEditTool(),
    ])

    # Web tools (Phase 10)
    try:
        from cc_python.tools.web_fetch import WebFetchTool
        tools.append(WebFetchTool())
    except ImportError:
        logger.debug("web_fetch tool not available (missing optional dependencies)")

    try:
        from cc_python.tools.web_search import WebSearchTool
        tools.append(WebSearchTool())
    except ImportError:
        logger.debug("web_search tool not available (missing optional dependencies)")

    # MCP 工具
    if mcp_manager and mcp_manager.is_connected:
        from cc_python.tools.mcp_tool import create_mcp_tools
        tools.extend(create_mcp_tools(mcp_manager))

        from cc_python.tools.list_mcp_resources import ListMcpResourcesTool
        from cc_python.tools.read_mcp_resource import ReadMcpResourceTool
        tools.append(ListMcpResourcesTool(manager=mcp_manager))
        tools.append(ReadMcpResourceTool(manager=mcp_manager))

    # Skill 工具
    from cc_python.skills import get_all_skills
    if get_all_skills():
        from cc_python.tools.skill_tool import SkillTool
        tools.append(SkillTool())

    return tools


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
