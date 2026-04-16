"""消息构造与规范化。

对应 TS: utils/messages.ts（5512 行）
Python 简化版保留核心：消息创建、tool_use/tool_result 构造、消息规范化（确保 user/assistant 交替）。

TS 版消息模型区分内部格式和 API 格式：
- 内部格式：Message（含 uuid, timestamp, type, isMeta 等元数据）
- API 格式：Anthropic/OpenAI 的 {role, content} 格式

Python 简化版直接使用 API 格式，不引入内部消息类型。
"""

from __future__ import annotations

import json
from typing import Any


def create_user_message(
        content: str | list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """创建 user 消息。

    对应 TS createUserMessage()。

    支持两种用途：
    1. 普通用户消息 → content 为字符串或 content blocks
    2. tool_result 消息 → content 为 tool_result blocks 列表
    """
    if tool_results:
        return {"role": "user", "content": tool_results}

    if content is None:
        content = "(empty message)"

    if isinstance(content, str) and not content:
        content = "(empty message)"

    return {"role": "user", "content": content}


def create_assistant_message(content: str) -> dict[str, Any]:
    """创建 assistant 消息。

    用于保存 API 返回的文本回复到消息历史。
    """
    return {"role": "assistant", "content": content}


def create_tool_use_assistant_message(
        text: str,
        tool_use_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """创建包含 tool_use 的 assistant 消息。

    对应 TS 中构造 assistant message 的逻辑（api.py 中已有类似实现，
    此处提供独立函数方便复用）。

    Anthropic API 格式：
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "..."},
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}},
            ...
        ]
    }
    """
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(tool_use_blocks)
    return {"role": "assistant", "content": content}


def create_tool_result_message(
        results: list[dict[str, Any]],
) -> dict[str, Any]:
    """创建 tool_result 的 user 消息。

    对应 TS 中将 tool_result 包装为 user message 的逻辑。

    Anthropic API 要求 tool_result 放在 role=user 的消息中：
    {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "...", "content": "..."},
            ...
        ]
    }
    """
    return {"role": "user", "content": results}


def normalize_messages_for_api(messages: list[dict]) -> list[dict]:
    """规范化消息列表为 API 格式。

    对应 TS normalizeMessagesForAPI()。

    确保：
    1. 没有 system 消息混入（system 通过 system 参数传递）
    2. user/assistant 角色交替（如果连续相同角色，合并 content）
    3. 空消息过滤
    4. compact-summary 消息保留
    """
    if not messages:
        return []

    result: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        # 跳过 system 消息
        if role == "system":
            continue

        # 跳过空消息
        if not content:
            continue

        # 检查是否需要和前一条消息合并（相同角色）
        if result and result[-1].get("role") == role:
            # 合并 content
            prev_content = result[-1].get("content")
            if isinstance(prev_content, str) and isinstance(content, str):
                result[-1]["content"] = prev_content + "\n" + content
            elif isinstance(prev_content, list) and isinstance(content, list):
                prev_content.extend(content)
            elif isinstance(prev_content, str) and isinstance(content, list):
                result[-1]["content"] = [{"type": "text", "text": prev_content}] + content
            elif isinstance(prev_content, list) and isinstance(content, str):
                prev_content.append({"type": "text", "text": content})
        else:
            result.append(dict(msg))

    return result


def messages_to_text(messages: list[dict]) -> str:
    """将消息列表转为纯文本（用于压缩摘要）。

    对应 TS 中的消息文本化逻辑。
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        parts.append(
                            f"[Tool call: {block.get('name', '')}({json.dumps(block.get('input', {}), ensure_ascii=False)})]"
                        )
                    elif btype == "tool_result":
                        parts.append(f"[Tool result: {str(block.get('content', ''))[:500]}]")
                    elif btype == "image":
                        parts.append("[Image]")
                    else:
                        parts.append(str(block)[:200])
                else:
                    parts.append(str(block))
            content = "\n".join(parts)

        lines.append(f"[{role}]: {content}")

    return "\n\n".join(lines)
