"""消息构造工具。

对应 TS: utils/messages.ts (createUserMessage, createAssistantMessage, normalizeMessagesForAPI)
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def create_user_message(content: str) -> dict:
    """对应 TS createUserMessage()。

    TS 源码 (utils/messages.ts:460):
      创建 UserMessage 对象，包含 type/message/uuid/timestamp 等字段。

    当前简化版：直接返回 Anthropic API 格式的 user message，
    后续添加工具调用时再扩展内部消息格式。
    """
    return {
        "role": "user",
        "content": content or "(empty message)",
    }


def create_assistant_message(content: str) -> dict:
    """对应 TS createAssistantAPIErrorMessage 等辅助函数。

    用于将 API 返回的 assistant 回复保存到消息历史中，
    以便下一轮对话时作为上下文传入。
    """
    return {
        "role": "assistant",
        "content": content,
    }


def normalize_messages_for_api(messages: list[dict]) -> list[dict]:
    """对应 TS normalizeMessagesForAPI()。

    TS 中此函数做了大量工作：过滤系统消息、压缩 tombstone、
    处理附件、确保 user/assistant 交替等。

    当前简化版：直接返回消息列表，因为我们的消息已经是 API 格式。
    后续扩展内部消息类型时，需要在此处做格式转换。
    """
    return list(messages)
