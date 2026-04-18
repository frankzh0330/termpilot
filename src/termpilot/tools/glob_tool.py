"""文件搜索工具（glob 模式匹配）。

对应 TS: tools/GlobTool/GlobTool.ts
"""

from __future__ import annotations

import asyncio
import glob as globmod
from pathlib import Path
from typing import Any


class GlobTool:
    """用 glob 模式搜索文件路径。

    is_concurrency_safe=True：只读操作，可并行。
    """

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "- Fast file pattern matching tool that works with any codebase size\n"
            "- Supports glob patterns like \"**/*.js\" or \"src/**/*.ts\"\n"
            "- Returns matching file paths sorted by modification time\n"
            "- Use this tool when you need to find files by name patterns\n"
            "- When you are doing an open ended search that may require multiple rounds "
            "of globbing and grepping, consider doing so systematically"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 '**/*.py' 或 'src/**/*.ts'",
                },
                "path": {
                    "type": "string",
                    "description": "搜索的根目录，默认为当前工作目录",
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
            return f"错误：目录不存在: {search_path}"

        def _glob() -> str:
            matches = globmod.glob(str(root / pattern), recursive=True)
            # 过滤掉目录，只保留文件
            files = [m for m in matches if Path(m).is_file()]
            if not files:
                return f"未找到匹配的文件: {pattern}"

            # 按修改时间排序
            files.sort(key=lambda f: Path(f).stat().st_mtime, reverse=True)

            # 截断过长结果
            max_results = 200
            truncated = len(files) > max_results
            files = files[:max_results]

            result = "\n".join(files)
            if truncated:
                result += f"\n... (共 {len(files)} 个结果，已截断)"
            return result

        try:
            return await asyncio.to_thread(_glob)
        except PermissionError:
            return f"错误：无权限搜索: {search_path}"
