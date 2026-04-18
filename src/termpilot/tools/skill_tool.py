"""Skill 工具。

对应 TS: tools/SkillTool/SkillTool.ts
让模型能够通过工具调用使用 skill。
模型调用此工具时，skill 的 prompt 内容被返回给模型作为上下文。
"""

from __future__ import annotations

from typing import Any


class SkillTool:
    """Skill 调用工具。

    模型通过此工具调用 skill，获取 skill 的 prompt 内容。
    """

    @property
    def name(self) -> str:
        return "skill"

    @property
    def description(self) -> str:
        return (
            "Execute a skill within the main conversation. "
            "Use this tool when the user references a 'slash command' or '/<something>'. "
            "The skill content expands into the current conversation as context."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "The skill name to invoke.",
                },
                "args": {
                    "type": "string",
                    "description": "Optional arguments for the skill.",
                },
            },
            "required": ["skill"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def call(self, **kwargs: Any) -> str:
        from termpilot.skills import find_skill

        skill_name = kwargs.get("skill", "")
        args = kwargs.get("args", "")

        if not skill_name:
            return "Error: skill name is required."

        skill = find_skill(skill_name)
        if not skill:
            return f"Error: skill '{skill_name}' not found."

        prompt = skill.get_prompt(args)
        return prompt
