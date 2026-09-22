"""流式响应渲染（从 cli.py 的 _stream_response_with_tools 提取）。

对应 TS query.ts 主循环 + REPL.tsx 的渲染逻辑：
把 api.query_with_tools 的事件流桥接到 QuietUI / session 存储，
并在结束后渲染完整 Markdown 响应与单轮费用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from termpilot.api import query_with_tools
from termpilot.permissions import PermissionContext
from termpilot.repl.permissions_ui import permission_prompt
from termpilot.session import SessionStorage
from termpilot.ui import QuietUI

logger = logging.getLogger(__name__)
console = Console()


async def stream_response_with_tools(
        client: Any,
        model: str,
        system_prompt: str,
        messages: list[dict],
        tools: list,
        storage: SessionStorage | None = None,
        permission_context: PermissionContext | None = None,
        session_id: str = "",
        cost_tracker: Any | None = None,
        ui: QuietUI | None = None,
        client_format: str = "openai",
        on_interactive_input: Any = None,
        is_current_turn: Any = None,
) -> str:
    """带工具调用的流式响应。

    使用回调实现实时渲染：
    - on_text: 文本流实时渲染 Markdown
    - on_tool_call: 显示工具调用过程和结果
    """
    logger.debug("stream_response_with_tools: model=%s, messages=%d, tools=%d",
                 model, len(messages), len(tools))
    full_response = ""

    def on_text(chunk: str) -> None:
        nonlocal full_response
        full_response += chunk

    def on_tool_call(name: str, input_data: dict, result: str) -> None:
        if is_current_turn and not is_current_turn():
            return
        # 记录工具调用到 session
        if storage:
            storage.record_tool_call(name, input_data, result)

    def on_assistant_message(text: str, tool_calls: list) -> None:
        if is_current_turn and not is_current_turn():
            return
        # 记录 assistant 中间消息到 session（确保崩溃可恢复）
        if storage and text and text.strip():
            storage.record_assistant_message(text)

    def on_event(event: dict[str, Any]) -> None:
        if is_current_turn and not is_current_turn():
            return
        if on_interactive_input:
            event_type = event.get("type")
            tool_name = event.get("name")
            if event_type == "permission_requested" or (
                    event_type == "tool_started"
                    and tool_name in {"ask_user_question", "exit_plan_mode"}
            ):
                on_interactive_input()
        if ui:
            ui.handle_event(event)

    if ui:
        ui.handle_event({"type": "status_started", "text": "Coalescing…"})
    try:
        full_response = await query_with_tools(
            client=client,
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_event=on_event,
            permission_context=permission_context,
            on_permission_ask=lambda tn, ti, m: permission_prompt(tn, ti, m, ui=ui),
            session_id=session_id,
            cost_tracker=cost_tracker,
            client_format=client_format,
            on_assistant_message=on_assistant_message,
        )
    except Exception:
        if ui:
            ui.handle_event({"type": "status_cleared"})
        raise

    if is_current_turn and not is_current_turn():
        if ui:
            ui.handle_event({"type": "status_cleared"})
        raise asyncio.CancelledError()

    # 最终渲染完整响应
    if full_response.strip():
        if ui:
            ui.handle_event({"type": "status_cleared"})
        console.print()
        console.print(Markdown(full_response))
    elif ui:
        ui.handle_event({"type": "status_cleared"})

    # 显示本轮费用
    if cost_tracker:
        total = cost_tracker.total_usage
        if total.total_tokens > 0:
            console.print()
            console.print(f"[dim]{cost_tracker.format_per_response(model, total)}[/]")

    return full_response
