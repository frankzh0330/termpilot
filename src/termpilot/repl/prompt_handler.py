"""prompt / slash 命令 / 后台通知的处理逻辑（从 cli.py 提取）。

handle_prompt        一个用户 turn 的完整编排：
                     hook → 附件 → trial workspace → API 调用 → 标题 → STOP hook
handle_slash_command slash 命令分发（Registry 在 commands.py，这里只做包装）
handle_task_notification 后台子 agent 完成通知
纯函数辅助（wait 检测 / 延迟判断）也在这里，cli.py re-export 保持兼容。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from rich.markdown import Markdown

from termpilot.attachments import process_attachments
from termpilot.commands import dispatch_command
from termpilot.hooks import HookEvent, dispatch_hooks
from termpilot.messages import create_assistant_message, create_user_message
from termpilot.queue import QueuedCommand
from termpilot.repl.state import InteractiveState
from termpilot.repl.stream_renderer import stream_response_with_tools
from termpilot.routing import build_routing_reminder
from termpilot.session import SessionStorage

logger = logging.getLogger(__name__)

# 需要独占 stdin 的命令：处理前先挂起主 prompt
INTERACTIVE_SLASH_COMMANDS = frozenset({"model", "rewind"})
# 会话状态类命令：assistant 正在等用户确认时延迟执行
STATE_CHANGING_SLASH_COMMANDS = frozenset({"clear", "compact", "rewind"})


# ---------------------------------------------------------------------------
# 纯函数辅助（cli.py re-export 保持既有导入路径兼容）
# ---------------------------------------------------------------------------

def assistant_appears_to_wait_for_user(text: str) -> bool:
    """Heuristic for assistant turns that end by asking the user to decide."""
    tail = text.strip()[-600:].lower()
    if not tail:
        return False
    if tail.endswith(("?", "？", "吗", "吗？")):
        return True
    wait_markers = (
        "confirm",
        "choose",
        "select",
        "which",
        "would you like",
        "should i",
        "确认",
        "选择",
        "哪",
        "是否",
        "要删除",
    )
    return any(marker in tail for marker in wait_markers)


def queued_slash_name(command: Any) -> str:
    value = getattr(command, "value", {})
    if isinstance(value, dict):
        return str(value.get("name", "")).lower()
    return ""


def should_defer_slash_for_user_reply(command: Any, awaiting_user_reply: bool) -> bool:
    """Delay state-changing slash commands queued during an assistant question."""
    if not awaiting_user_reply:
        return False
    if getattr(command, "mode", "") != "slash_command":
        return False
    value = getattr(command, "value", {})
    if not isinstance(value, dict) or not value.get("queued_during_active_turn"):
        return False
    return queued_slash_name(command) in STATE_CHANGING_SLASH_COMMANDS


def print_connection_error(console: Any, exc: Exception) -> None:
    """打印连接失败的友好提示。"""
    from termpilot.config import get_settings_path
    settings_path = get_settings_path()
    console.print(
        f"[red]Failed to connect to LLM API.[/]\n\n"
        f"Check [bold]{settings_path}[/]:\n"
        f"  - API key is valid and active\n"
        f"  - Base URL is correct\n"
        f"  - Network is accessible\n\n"
        f"Tip: run [bold]termpilot model[/] to reconfigure.\n\n"
        f"[dim]Error: {exc}[/]"
    )


# ---------------------------------------------------------------------------
# 依赖容器
# ---------------------------------------------------------------------------

@dataclass
class ReplDeps:
    """REPL 处理器的协作对象（由 cli.py 组装注入）。"""

    console: Any
    ui: Any
    storage: SessionStorage
    tools: list
    mcp_manager: Any
    cost_tracker: Any
    queue: Any
    state: InteractiveState
    # /model 等命令后刷新 client/model/system_prompt（更新 state 字段）
    refresh_runtime: Callable[[], str]
    # 交互式工具要读 stdin 时暂停主 prompt
    suspend_input: Callable[[], None]


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

async def handle_prompt(cmd: QueuedCommand, deps: ReplDeps) -> None:
    """处理 prompt 命令：hook → 附件 → API 调用。"""
    state = deps.state
    console = deps.console
    storage = deps.storage
    user_input = cmd.value

    # UserPromptSubmit Hook
    hook_results = await dispatch_hooks(
        event=HookEvent.USER_PROMPT_SUBMIT,
        session_id=storage.session_id or "",
        prompt=user_input,
    )
    blocked = False
    for hr in hook_results:
        if hr.exit_code == 2:
            console.print(f"[yellow]Hook blocked prompt: {hr.stderr or 'blocked'}[/]")
            blocked = True
            break
    if blocked:
        return

    hook_feedback = [hr.stdout for hr in hook_results if hr.exit_code == 0 and hr.stdout.strip()]
    effective_input = user_input
    if hook_feedback:
        effective_input += "\n\n<user-prompt-submit-hook>\n" + "\n".join(
            hook_feedback) + "\n</user-prompt-submit-hook>"
    routing_reminder = build_routing_reminder(user_input)
    if routing_reminder:
        effective_input += f"\n\n{routing_reminder}"

    from termpilot.workspace import (
        TrialWorkspaceManager,
        decide_trial_workspace,
        get_active_trial_workspace,
        get_trial_workspace_config,
        set_active_trial_workspace,
    )
    active_trial_workspace = get_active_trial_workspace()
    if active_trial_workspace is None and state.permission_context.mode.value != "plan":
        trial_config = get_trial_workspace_config()
        trial_decision = decide_trial_workspace(user_input, trial_config)
        if trial_decision.should_start:
            try:
                trial_workspace = TrialWorkspaceManager(trial_config).create(
                    purpose=user_input[:160],
                )
                set_active_trial_workspace(trial_workspace)
                active_trial_workspace = trial_workspace
                console.print(
                    f"[dim]Trial workspace started automatically: {trial_workspace.id}[/dim]"
                )
            except Exception as exc:
                logger.warning("failed to auto-start trial workspace: %s", exc)

    attachment_blocks = process_attachments(effective_input)
    if attachment_blocks:
        content_blocks = [{"type": "text", "text": effective_input}] + attachment_blocks
        state.messages.append(create_user_message(content_blocks))
    else:
        state.messages.append(create_user_message(effective_input))
    storage.record_user_message(user_input)

    if state.permission_context.mode.value == "plan":
        state.messages.append({
            "role": "user",
            "content": (
                "<system-reminder>"
                "You are in plan mode (read-only). Do NOT attempt to write, edit, "
                "or modify any files. Only use-only tools: read_file, glob, grep, "
                "bash (read-only only). When ready, call exit_plan_mode with your plan."
                "</system-reminder>"
            ),
        })
    active_trial_workspace = get_active_trial_workspace()
    if active_trial_workspace is not None:
        state.messages.append({
            "role": "user",
            "content": (
                "<system-reminder>"
                "Trial workspace mode is active. Tool reads, writes, edits, searches, and bash commands "
                "are redirected to an isolated trial workspace, not directly to the source project. "
                f"Source project: {active_trial_workspace.source_cwd}. "
                f"Trial workspace: {active_trial_workspace.workspace_path}. "
                "Tell the user to review with /trial diff and apply with /trial apply when appropriate."
                "</system-reminder>"
            ),
        })

    logger.debug("sending to API: %d messages in context", len(state.messages))

    run_id = state.next_turn()
    try:
        full_response = await stream_response_with_tools(
            state.client, state.model, state.system_prompt, state.messages, deps.tools, storage,
            permission_context=state.permission_context,
            session_id=storage.session_id or "",
            cost_tracker=deps.cost_tracker,
            ui=deps.ui,
            client_format=state.client_format,
            on_interactive_input=deps.suspend_input,
            is_current_turn=lambda: state.is_current_turn(run_id),
        )
    except Exception as api_exc:
        print_connection_error(console, api_exc)
        return

    state.messages.append({**create_assistant_message(full_response), "_timestamp": time.time()})
    storage.record_assistant_message(full_response)
    state.awaiting_user_reply = assistant_appears_to_wait_for_user(full_response)
    logger.debug("response received: %d chars, total messages: %d",
                 len(full_response), len(state.messages))

    if not state.title_generated and len(state.messages) >= 2:
        from termpilot.session import generate_session_title
        title = await generate_session_title(
            state.messages, state.client, state.model, state.client_format)
        if title:
            storage.save_metadata("custom-title", title)
            logger.debug("session title generated: %s", title)
        state.title_generated = True

    await dispatch_hooks(
        event=HookEvent.STOP,
        session_id=storage.session_id or "",
    )


async def handle_slash_command(cmd: QueuedCommand, deps: ReplDeps) -> None:
    """串行处理 slash command，避免与正在运行的 turn 并发修改上下文。"""
    state = deps.state
    console = deps.console
    value = cmd.value if isinstance(cmd.value, dict) else {}
    cmd_name = str(value.get("name", ""))
    cmd_args = str(value.get("args", ""))
    if not cmd_name:
        return

    logger.debug("slash command: /%s %s", cmd_name, cmd_args[:50])
    if cmd_name in INTERACTIVE_SLASH_COMMANDS:
        deps.suspend_input()
    cmd_context = {
        "messages": state.messages,
        "system_prompt": state.system_prompt,
        "client": state.client,
        "model": state.model,
        "mcp_manager": deps.mcp_manager,
        "ui": deps.ui,
        "client_format": state.client_format,
        "refresh_runtime": deps.refresh_runtime,
        "storage": deps.storage,
    }
    result = await dispatch_command(cmd_name, cmd_args, cmd_context)
    logger.debug(
        "command result: exit_repl=%s, should_query=%s, output=%d chars",
        result.exit_repl,
        result.should_query,
        len(result.output),
    )

    if result.exit_repl:
        console.print("[dim]再见！[/]")
        state.exit_flag.set()
        return

    if result.output:
        console.print()
        console.print(Markdown(result.output))

    if result.new_messages is not None:
        if len(result.new_messages) == 0:
            state.messages.clear()
            if cmd_name == "clear":
                dropped = deps.queue.discard(
                    lambda queued: (
                        queued.mode == "prompt"
                        and queued.origin == "user"
                        and queued.agent_id == ""
                    )
                )
                if dropped:
                    logger.debug("clear discarded %d pending user prompts", dropped)
            console.print("[dim]对话已清除[/]")
        else:
            state.messages[:] = result.new_messages

    if result.should_query:
        state.messages.append(create_user_message(result.output))
        deps.storage.record_user_message(result.output)
        run_id = state.next_turn()
        try:
            full_response = await stream_response_with_tools(
                state.client, state.model, state.system_prompt, state.messages, deps.tools, deps.storage,
                permission_context=state.permission_context,
                session_id=deps.storage.session_id or "",
                cost_tracker=deps.cost_tracker,
                ui=deps.ui,
                client_format=state.client_format,
                on_interactive_input=deps.suspend_input,
                is_current_turn=lambda: state.is_current_turn(run_id),
            )
        except Exception as api_exc:
            print_connection_error(console, api_exc)
        else:
            state.messages.append({**create_assistant_message(full_response), "_timestamp": time.time()})
            deps.storage.record_assistant_message(full_response)
            state.awaiting_user_reply = assistant_appears_to_wait_for_user(full_response)
            await dispatch_hooks(
                event=HookEvent.STOP,
                session_id=deps.storage.session_id or "",
            )


def handle_task_notification(cmd: QueuedCommand, deps: ReplDeps) -> None:
    """处理后台子 agent 完成通知。"""
    state = deps.state
    console = deps.console
    data = cmd.value if isinstance(cmd.value, dict) else {}
    agent_id = data.get("agent_id", "?")
    subagent_type = data.get("subagent_type", "agent")
    status = data.get("status", "unknown")

    if status == "completed":
        summary = str(data.get("summary", ""))
        result_path = str(data.get("result_path", ""))
        original_size = data.get("original_size", 0)
        console.print(f"\n[green]Agent {subagent_type} ({agent_id}) completed[/]")
        if summary:
            console.print(Markdown(summary))
        if result_path:
            console.print(f"[dim]Full result saved to: {result_path}[/]")
        handoff = (
            f"[Background agent {subagent_type}/{agent_id} completed]\n"
            f"Summary:\n{summary or '(no summary)'}\n\n"
            f"Full result path: {result_path or '(not saved)'}\n"
            f"Original size: {original_size} characters\n"
            "Use read_file on the result path if more detail is needed."
        )
        state.messages.append(create_assistant_message(handoff))
        deps.storage.record_assistant_message(handoff)
    else:
        error = data.get("error", "unknown error")
        console.print(f"\n[red]Agent {subagent_type} ({agent_id}) failed: {error}[/]")
