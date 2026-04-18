"""Enter Plan Mode 工具。

对应 TS: tools/EnterPlanModeTool/
请求进入规划模式，模型在此模式下只做只读探索，不做修改。
"""

from __future__ import annotations

from typing import Any


class EnterPlanModeTool:
    """进入规划模式。"""

    @property
    def name(self) -> str:
        return "enter_plan_mode"

    @property
    def description(self) -> str:
        return (
            "Requests permission to enter plan mode for complex tasks requiring "
            "exploration and design before implementation. In plan mode, you can "
            "only read files and explore the codebase — no modifications allowed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    async def call(self, **kwargs: Any) -> str:
        return (
            "Plan mode activated. You now have READ-ONLY access.\n\n"
            "Guidelines:\n"
            "- Explore the codebase thoroughly using read_file, glob, grep, bash (read-only)\n"
            "- Design an implementation approach\n"
            "- Use exit_plan_mode when you're ready to present your plan\n\n"
            "Remember: Do NOT create, modify, or delete any files while in plan mode."
        )
