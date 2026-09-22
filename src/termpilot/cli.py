"""CLI 入口。

对应 TS: main.tsx (CLI 参数解析、启动逻辑) + entrypoints/cli.tsx
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from termpilot.api import create_client
from termpilot.config import ensure_settings_template, get_config_home, get_effective_model
from termpilot.context import build_system_prompt
from termpilot.hooks import HookEvent, dispatch_hooks
from termpilot.mcp import MCPManager
from termpilot.messages import create_assistant_message, create_user_message
from termpilot.permissions import (
    PermissionMode,
    PermissionResult,
    build_permission_context,
)
from termpilot.prompt_utils import ask_with_esc
from termpilot.session import SessionStorage, list_sessions, load_session
from termpilot.skills import discover_and_load_skills
from termpilot.tools import get_all_tools
from termpilot.ui import QuietUI

DEFAULT_MODEL = "gpt-4o"
INTERACTIVE_SLASH_COMMANDS = frozenset({"model", "rewind"})
STATE_CHANGING_SLASH_COMMANDS = frozenset({"clear", "compact", "rewind"})

# repl 子系统 re-export（P1-2 重构：实现搬到 termpilot.repl.*，此处保留旧导入路径）
from termpilot.repl.permissions_ui import (  # noqa: E402,F401
    ask_permission_choice as _ask_permission_choice_impl,
    permission_prompt as _permission_prompt_impl,
    permission_result_from_choice as _permission_result_from_choice_impl,
)
from termpilot.repl.prompt_handler import (  # noqa: E402,F401
    assistant_appears_to_wait_for_user,
    queued_slash_name,
    should_defer_slash_for_user_reply,
)
from termpilot.repl.stream_renderer import (  # noqa: E402,F401
    stream_response_with_tools,
)

console = Console()
logger = logging.getLogger(__name__)


def _assistant_appears_to_wait_for_user(text: str) -> bool:
    """Heuristic for assistant turns that end by asking the user to decide."""
    return assistant_appears_to_wait_for_user(text)


def _queued_slash_name(command: Any) -> str:
    return queued_slash_name(command)


def _should_defer_slash_for_user_reply(command: Any, awaiting_user_reply: bool) -> bool:
    """Delay state-changing slash commands queued during an assistant question."""
    return should_defer_slash_for_user_reply(command, awaiting_user_reply)


def _permission_result_from_choice(tool_name: str, choice: Any) -> PermissionResult:
    """Map permission menu output to a permission result."""
    return _permission_result_from_choice_impl(tool_name, choice)


def _ask_permission_choice() -> str | None:
    """Ask for permission using stable numeric input."""
    return _ask_permission_choice_impl()


async def _permission_prompt(
        tool_name: str,
        tool_input: dict,
        message: str,
        ui: QuietUI | None = None,
) -> PermissionResult:
    """权限确认提示（实现见 termpilot.repl.permissions_ui）。"""
    return await _permission_prompt_impl(tool_name, tool_input, message, ui=ui)


async def _stream_response_with_tools(
        *args: Any, **kwargs: Any,
) -> str:
    """带工具调用的流式响应（实现见 termpilot.repl.stream_renderer）。"""
    return await stream_response_with_tools(*args, **kwargs)


async def _async_single_prompt(prompt: str, model: str, *, json_summary: bool = False) -> None:
    """单次 prompt 模式。"""
    logger.debug("=== single_prompt mode: model=%s, prompt=%r", model, prompt[:100])

    storage = SessionStorage()
    ui = QuietUI(console)
    storage.start_session()
    logger.debug("session started: %s", storage.session_id)

    # 初始化 Undo 系统
    from termpilot.undo import init_undo, cleanup_stale_snapshots
    init_undo(storage.session_id)
    cleanup_stale_snapshots()

    # SessionStart Hook
    await dispatch_hooks(
        event=HookEvent.SESSION_START,
        session_id=storage.session_id or "",
    )

    # 初始化 MCP
    mcp_manager = MCPManager()
    await mcp_manager.discover_and_connect()

    # 加载 skills
    discover_and_load_skills()

    client, client_format = create_client()
    logger.debug("client created")
    tools = get_all_tools(mcp_manager=mcp_manager)
    enabled_tools = {t.name for t in tools}
    logger.debug("tools: %d enabled (%s)", len(tools), ", ".join(sorted(enabled_tools)[:10]))
    permission_context = build_permission_context()
    logger.debug("permission mode: %s", permission_context.mode.value)

    system_prompt = build_system_prompt(
        model=model,
        enabled_tools=enabled_tools,
        mcp_manager=mcp_manager,
    )
    logger.debug("system prompt built: %d chars", len(system_prompt))

    # UserPromptSubmit Hook
    hook_results = await dispatch_hooks(
        event=HookEvent.USER_PROMPT_SUBMIT,
        session_id=storage.session_id or "",
        prompt=prompt,
    )
    # 检查是否被 hook 阻断
    for hr in hook_results:
        if hr.exit_code == 2:
            console.print(f"[yellow]Hook blocked prompt: {hr.stderr or 'blocked'}[/]")
            return
    # 注入 hook 反馈
    hook_feedback = [hr.stdout for hr in hook_results if hr.exit_code == 0 and hr.stdout.strip()]
    effective_prompt = prompt
    if hook_feedback:
        effective_prompt += "\n\n<user-prompt-submit-hook>\n" + "\n".join(
            hook_feedback) + "\n</user-prompt-submit-hook>"

    messages = [create_user_message(effective_prompt)]

    storage.record_user_message(prompt)
    logger.debug("sending single prompt to API (%d chars)", len(effective_prompt))

    from termpilot.token_tracker import CostTracker
    cost_tracker = CostTracker()

    try:
        response = await _stream_response_with_tools(
            client, model, system_prompt, messages, tools, storage,
            permission_context=permission_context,
            session_id=storage.session_id or "",
            cost_tracker=cost_tracker,
            ui=ui,
            client_format=client_format,
        )
    except Exception as api_exc:
        _print_connection_error(api_exc)
        return

    storage.record_assistant_message(response)
    logger.debug("single prompt response: %d chars", len(response))

    # 生成会话标题
    messages.append(create_assistant_message(response))
    from termpilot.session import generate_session_title
    title = await generate_session_title(messages, client, model, client_format)
    if title:
        storage.save_metadata("custom-title", title)
        logger.debug("session title: %s", title)

    if json_summary:
        usage = cost_tracker.total_usage
        console.print(json.dumps({
            "session_id": storage.session_id or "",
            "model": model,
            "response_chars": len(response),
            "input_tokens": usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "cost_usd": round(cost_tracker.get_total_cost(), 6),
        }, ensure_ascii=False))

    # Stop Hook
    await dispatch_hooks(
        event=HookEvent.STOP,
        session_id=storage.session_id or "",
    )

    console.print()


def _pick_session(sessions: list[dict]) -> str | None:
    """让用户从历史会话中选择一个。"""
    if not sessions:
        console.print("[yellow]没有找到历史会话。[/]")
        return None

    table = Table(title="历史会话")
    table.add_column("#", style="dim", width=4)
    table.add_column("会话ID", style="cyan", width=12)
    table.add_column("标题", width=30)
    table.add_column("首条消息", width=30)
    table.add_column("消息数", justify="right", width=6)

    for i, s in enumerate(sessions[:20], 1):
        title = s.get("title", "")[:30]
        table.add_row(
            str(i),
            s.get("session_id", "")[:8] + "...",
            title or s.get("first_prompt", "")[:30],
            s.get("first_prompt", "")[:30] if title else "",
            str(s.get("message_count", 0)),
        )
    console.print(table)

    try:
        import questionary as _q
        choice = ask_with_esc(_q.text("选择会话编号（直接回车取消）:")) or ""
        if not choice.strip():
            return None
        idx = int(choice.strip()) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx].get("session_id")
    except (ValueError, KeyboardInterrupt):
        pass
    return None


def _print_connection_error(exc: Exception) -> None:
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


async def _async_interactive(model: str, resume_session_id: str | None = None) -> None:
    """交互循环模式（composition root）。

    P1-2 重构后只负责组装 repl 子系统（state / InputHandler / REPLLoop /
    prompt handlers），业务逻辑在 termpilot.repl 包内，可独立测试。
    """
    from termpilot.repl.input_handler import InputHandler
    from termpilot.repl.loop import REPLLoop
    from termpilot.repl.prompt_handler import (
        ReplDeps,
        handle_prompt,
        handle_slash_command,
        handle_task_notification,
    )
    from termpilot.repl.state import InteractiveState

    logger.debug("=== interactive mode: model=%s, resume_session_id=%s", model, resume_session_id)
    storage = SessionStorage()
    ui = QuietUI(console)

    if resume_session_id:
        # 恢复模式 — 加载历史消息
        history_messages = load_session(resume_session_id)
        storage.start_session(resume_session_id)
        logger.debug("resumed session %s: %d history messages", resume_session_id[:8], len(history_messages))
        console.print(f"[dim]已恢复会话: {resume_session_id[:8]}... ({len(history_messages)} 条历史消息)[/]")
    else:
        history_messages = []
        storage.start_session()
        logger.debug("new session: %s", storage.session_id)

    # 初始化 Undo 系统
    from termpilot.undo import init_undo, cleanup_stale_snapshots
    init_undo(storage.session_id)
    cleanup_stale_snapshots()

    # SessionStart Hook
    await dispatch_hooks(
        event=HookEvent.SESSION_START,
        session_id=storage.session_id or "",
    )

    # 初始化 MCP
    mcp_manager = MCPManager()
    await mcp_manager.discover_and_connect()

    # 加载 skills
    discover_and_load_skills()

    client, client_format = create_client()
    logger.debug("client created")
    tools = get_all_tools(mcp_manager=mcp_manager)
    enabled_tools = {t.name for t in tools}
    logger.debug("tools: %d enabled (%s)", len(tools), ", ".join(sorted(enabled_tools)[:10]))
    permission_context = build_permission_context()
    logger.debug("permission mode: %s, working_dir=%s", permission_context.mode.value,
                 permission_context.working_directory)

    system_prompt = build_system_prompt(
        model=model,
        enabled_tools=enabled_tools,
        mcp_manager=mcp_manager,
    )
    logger.debug("system prompt built: %d chars", len(system_prompt))

    from termpilot.token_tracker import CostTracker
    cost_tracker = CostTracker()

    # ── 共享状态（替代原先的 nonlocal 闭包变量）──
    state = InteractiveState(
        messages=list(history_messages),
        client=client,
        client_format=client_format,
        model=model,
        system_prompt=system_prompt,
        permission_context=permission_context,
    )

    def refresh_runtime() -> str:
        state.client, state.client_format = create_client()
        state.model = get_effective_model(DEFAULT_MODEL)
        state.system_prompt = build_system_prompt(
            model=state.model,
            enabled_tools=enabled_tools,
            mcp_manager=mcp_manager,
        )
        logger.debug("runtime refreshed after /model: model=%s, format=%s", state.model, state.client_format)
        return state.model

    # 构建 MCP 状态信息
    mcp_info = ""
    if mcp_manager.is_connected:
        mcp_tools = mcp_manager.get_tools()
        if mcp_tools:
            mcp_info = f"\nMCP: {len(mcp_tools)} 工具 ({', '.join(t['full_name'] for t in mcp_tools[:3])}{'...' if len(mcp_tools) > 3 else ''})"

    console.print(
        Panel(
            Text.from_markup(
                f"[bold]TermPilot[/] — model: {model}\n"
                f"工具: {', '.join(t.name for t in tools[:6])}{'...' if len(tools) > 6 else ''}\n"
                f"权限模式: {permission_context.mode.value}\n"
                f"会话: {storage.session_id[:8] if storage.session_id else 'N/A'}...{mcp_info}\n"
                f"输入消息开始对话，/help 查看命令，Ctrl+C 退出\n"
                f"Shift+Tab 切换 Plan Mode（只读规划）"
            ),
            border_style="blue",
        )
    )

    # ── UI：prompt_toolkit ──
    from termpilot.completer import SlashCompleter
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PtStyle

    slash_completer = SlashCompleter()
    slash_completer.refresh()
    pt_style = PtStyle.from_dict({
        "prompt": "bold green",
        "plan-prompt": "bold #ff8800",
        "edits-prompt": "bold #00aa66",
    })

    def _get_prompt_message():
        if state.permission_context.mode == PermissionMode.PLAN:
            return [("class:plan-prompt", "plan"), ("class:prompt", " > ")]
        if state.permission_context.mode.value == "acceptEdits":
            return [("class:edits-prompt", "edits"), ("class:prompt", " > ")]
        return [("class:prompt", "> ")]

    kb = KeyBindings()

    def _cleanup_interrupted_work() -> None:
        from termpilot.queue import cancel_running_agents
        from termpilot.tools.task import clear_incomplete_tasks

        queue.discard(lambda queued: queued.origin in {"agent", "task-watcher"})
        cancel_running_agents()
        clear_incomplete_tasks()

    @kb.add("s-tab")
    def _cycle_mode(event):
        from termpilot.permissions import cycle_permission_mode
        next_mode = cycle_permission_mode(state.permission_context)
        state.permission_context.mode = next_mode
        event.app.invalidate()

    @kb.add("escape", eager=True)
    def _interrupt_or_clear(event):
        if state.is_processing:
            state.invalidate_current_turn()
            _cleanup_interrupted_work()
            state.active_processing_task.cancel()
            ui.clear_status()
            console.print("\n[yellow]Interrupted current response.[/]")
            event.app.current_buffer.reset()
            event.app.invalidate()
            return
        event.app.current_buffer.reset()

    history_file = get_config_home() / "prompt_history"
    pt_session = PromptSession(
        message=_get_prompt_message,
        completer=slash_completer,
        complete_while_typing=True,
        style=pt_style,
        history=FileHistory(str(history_file)),
        enable_history_search=True,
        key_bindings=kb,
    )

    # ── 组装 repl 子系统 ──
    from termpilot.queue import get_main_queue

    queue = get_main_queue()

    input_handler = InputHandler(pt_session, queue, state, console)

    deps = ReplDeps(
        console=console,
        ui=ui,
        storage=storage,
        tools=tools,
        mcp_manager=mcp_manager,
        cost_tracker=cost_tracker,
        queue=queue,
        state=state,
        refresh_runtime=refresh_runtime,
        suspend_input=input_handler.suspend,
    )

    drain_loop = REPLLoop(state, queue, deps)
    drain_loop.register("prompt", handle_prompt)
    drain_loop.register("slash_command", handle_slash_command)
    drain_loop.register("task_notification", handle_task_notification)

    # ── 启动 collector + drain 并发运行 ──
    await asyncio.gather(
        input_handler.collect_loop(),
        drain_loop.run(),
        return_exceptions=True,
    )

    # 显示费用汇总
    if cost_tracker.total_usage.total_tokens > 0:
        console.print()
        console.print(f"[dim]{cost_tracker.format_report()}[/]")

    # 清理 MCP 连接
    await mcp_manager.shutdown()





def _setup_logging() -> None:
    """配置日志到文件，不影响终端交互。

    对齐 TS 版设计：
    - 日志写文件，不写 stderr（不干扰 Rich UI）
    - 按 session 分文件：~/.termpilot/debug/<sessionId>.txt
    - latest 软链接指向当前会话，方便 tail -f
    - 环境变量 CC_PYTHON_LOG_LEVEL 控制级别
    """
    import os
    import uuid

    log_level_str = os.environ.get("CC_PYTHON_LOG_LEVEL", "DEBUG").upper()
    log_level = getattr(logging, log_level_str, logging.DEBUG)

    log_dir = get_config_home() / "debug"
    log_dir.mkdir(parents=True, exist_ok=True)

    session_id = str(uuid.uuid4())[:8]
    log_file = log_dir / f"{session_id}.txt"

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger = logging.getLogger("termpilot")
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # latest 软链接指向当前会话
    latest_link = log_dir / "latest"
    try:
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(log_file)
    except OSError:
        pass

    # 静默第三方库的日志
    for noisy in ("httpx", "httpcore", "openai", "anthropic", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root_logger.info("=== termpilot 启动 (session: %s) ===", session_id)


def _check_update() -> None:
    """检查 PyPI 上是否有新版本，有则提示升级。

    使用缓存的检查结果（~/.termpilot/.update-check），每天最多查一次。
    """
    import json
    import urllib.request
    from packaging.version import Version
    from termpilot import __version__
    from termpilot.config import get_config_home

    cache_file = get_config_home() / ".update-check"

    def _is_outdated(latest: str) -> bool:
        try:
            return Version(latest) > Version(__version__)
        except Exception:
            return False

    now_day = time.strftime("%Y-%m-%d")
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("day") == now_day:
                latest = cached.get("latest", "")
                if _is_outdated(latest):
                    console.print(f"[dim]⚠️  termpilot {__version__} is outdated. Latest: {latest}[/]")
                    console.print(f"[dim]   Run: pip install -U termpilot[/]\n")
                return
        except (json.JSONDecodeError, KeyError):
            pass

    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/termpilot/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            latest = data.get("info", {}).get("version", "")

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"day": now_day, "latest": latest}), encoding="utf-8")

        if _is_outdated(latest):
            console.print(f"[dim]⚠️  termpilot {__version__} is outdated. Latest: {latest}[/]")
            console.print(f"[dim]   Run: pip install -U termpilot[/]\n")
    except Exception:
        pass


@click.group(invoke_without_command=True)
@click.option(
    "--prompt", "-p",
    default=None,
    help="直接传入一条 prompt，不进入交互模式",
)
@click.option(
    "--model", "-m",
    default=None,
    help="模型名称 (默认从 settings.json 或 claude-sonnet-4-20250514)",
)
@click.option(
    "--resume", "-r", "resume",
    is_flag=True,
    default=False,
    help="恢复上一次会话继续对话",
)
@click.option(
    "--session", "-s", "session_id",
    default=None,
    help="指定要恢复的会话 ID",
)
@click.option(
    "--permission-mode",
    type=click.Choice([mode.value for mode in PermissionMode]),
    default=None,
    help="Override permission mode for this run (useful for eval harnesses)",
)
@click.option(
    "--cwd",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Run TermPilot from this working directory",
)
@click.option(
    "--json-summary",
    is_flag=True,
    default=False,
    help="Print a machine-readable JSON summary after one-shot mode",
)
@click.pass_context
def main(
        ctx: click.Context,
        prompt: str | None,
        model: str | None,
        resume: bool,
        session_id: str | None,
        permission_mode: str | None,
        cwd: Path | None,
        json_summary: bool,
) -> None:
    """TermPilot — AI 编程助手。"""
    if ctx.invoked_subcommand is not None:
        return
    _setup_logging()
    _check_update()
    ensure_settings_template()
    if cwd is not None:
        os.chdir(cwd.expanduser().resolve())
    if permission_mode:
        os.environ["TERMPILOT_PERMISSION_MODE"] = permission_mode

    resolved_model = model or get_effective_model(DEFAULT_MODEL)
    logger.debug("=== main() called: prompt=%s, model=%s, resume=%s, session_id=%s ===",
                 "yes" if prompt else None, resolved_model, resume, session_id)

    # 确定 resume 的 session_id
    effective_session_id = session_id

    if resume and not effective_session_id:
        sessions = list_sessions()
        effective_session_id = _pick_session(sessions)

    if prompt:
        asyncio.run(_async_single_prompt(prompt, resolved_model, json_summary=json_summary))
    else:
        if json_summary:
            raise click.UsageError("--json-summary is only supported with --prompt/-p")
        asyncio.run(_async_interactive(resolved_model, effective_session_id))


@main.command(name="model")
def model_cmd() -> None:
    """Configure LLM provider and model interactively."""
    from termpilot.config import run_setup_wizard
    run_setup_wizard()


@main.command(name="setup")
def setup_cmd() -> None:
    """Configure LLM provider and API key interactively."""
    from termpilot.config import run_setup_wizard
    run_setup_wizard()


if __name__ == "__main__":
    main()
