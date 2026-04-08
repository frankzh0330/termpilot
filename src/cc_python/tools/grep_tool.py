"""内容搜索工具（grep 风格）。

对应 TS: tools/GrepTool/GrepTool.ts
使用 Python re 模块实现，不依赖外部 ripgrep。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from cc_python.tools.base import Tool


def _should_search(path: Path) -> bool:
    """判断是否应该搜索此文件（跳过二进制/隐藏/常见忽略目录）。"""
    # 跳过隐藏目录和文件
    parts = path.parts
    if any(p.startswith(".") for p in parts):
        return False
    # 跳过常见非文本目录
    skip_dirs = {"node_modules", "__pycache__", ".git", ".venv", "venv", "dist", "build"}
    if skip_dirs.intersection(set(parts)):
        return False
    # 简单二进制检测
    try:
        suffix = path.suffix.lower()
        binary_exts = {".pyc", ".so", ".dylib", ".dll", ".exe", ".png", ".jpg",
                       ".jpeg", ".gif", ".zip", ".tar", ".gz", ".woff", ".ttf", ".ico"}
        if suffix in binary_exts:
            return False
    except Exception:
        pass
    return True


class GrepTool:
    """搜索文件内容中的模式匹配。

    is_concurrency_safe=True：只读操作，可并行。
    """

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "A powerful search tool for searching file contents.\n"
            "\n"
            "Usage:\n"
            "- ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command.\n"
            "- Supports full regex syntax (e.g., \"log.*Error\", \"function\\s+\\w+\")\n"
            "- Filter files with path parameter to search in a specific directory\n"
            "- Returns matching lines with line numbers and file paths\n"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "要搜索的正则表达式模式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索的目录或文件路径，默认为当前工作目录",
                },
            },
            "required": ["pattern"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern", "")
        search_path = kwargs.get("path") or "."

        if not pattern:
            return "错误：pattern 不能为空"

        root = Path(search_path).expanduser()
        if not root.exists():
            return f"错误：路径不存在: {search_path}"

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"错误：无效的正则表达式: {e}"

        def _grep() -> str:
            results = []
            max_results = 100

            if root.is_file():
                files_to_search = [root]
            else:
                files_to_search = [f for f in root.rglob("*") if f.is_file() and _should_search(f)]

            for file_path in files_to_search:
                if len(results) >= max_results:
                    break
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    for line_no, line in enumerate(text.splitlines(), 1):
                        if regex.search(line):
                            results.append(f"{file_path}:{line_no}: {line.strip()}")
                            if len(results) >= max_results:
                                break
                except (PermissionError, OSError):
                    continue

            if not results:
                return f"未找到匹配: {pattern}"

            output = "\n".join(results)
            if len(results) >= max_results:
                output += f"\n... (结果已截断，最多显示 {max_results} 条)"
            return output

        try:
            return await asyncio.to_thread(_grep)
        except PermissionError:
            return f"错误：无权限搜索: {search_path}"
