"""Exit Plan Mode 工具。

对应 TS: tools/ExitPlanModeTool/
退出规划模式，返回正常执行模式。模型的计划将展示给用户审批。
"""

from __future__ import annotations

from typing import Any


class ExitPlanModeTool:
    """退出规划模式。"""

    @property
    def name(self) -> str:
        return "exit_plan_mode"

    @property
    def description(self) -> str:
        return (
            "Exit plan mode after completing exploration and design. "
            "Your plan will be presented to the user for approval before implementation begins."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    async def call(self, **kwargs: Any) -> str:
        return (
            "Plan mode deactivated. Returning to normal execution mode.\n\n"
            "The plan has been noted. Proceed with implementation based on the exploration done."
        )
