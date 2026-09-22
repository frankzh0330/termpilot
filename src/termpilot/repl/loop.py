"""REPL 主处理循环（从 cli.py 的 _drain_loop 提取）。

REPLLoop 只做三件事：dequeue → 按 mode 分发给注册的 handler →
处理中断与 task-watcher 自动接续。handler 本身（prompt/slash/通知）
由 cli.py 组装时注入（Strategy 模式），循环不感知具体业务。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from termpilot.queue import Priority, QueuedCommand
from termpilot.repl.prompt_handler import ReplDeps, should_defer_slash_for_user_reply

logger = logging.getLogger(__name__)

Handler = Callable[[QueuedCommand, ReplDeps], Awaitable[None]]


class REPLLoop:
    """主处理循环：dequeue → 分发到 handler → 检查后台任务。"""

    def __init__(self, state: Any, queue: Any, deps: ReplDeps):
        self._state = state
        self._queue = queue
        self._deps = deps
        self._handlers: dict[str, Handler] = {}

    def register(self, mode: str, handler: Handler) -> None:
        self._handlers[mode] = handler

    def _is_main_thread_command(self, cmd: QueuedCommand) -> bool:
        """主线程只处理发给主线程的队列命令。"""
        if cmd.agent_id != "":
            return False
        return not should_defer_slash_for_user_reply(cmd, self._state.awaiting_user_reply)

    def _cleanup_interrupted_work(self) -> None:
        from termpilot.queue import cancel_running_agents
        from termpilot.tools.task import clear_incomplete_tasks

        self._queue.discard(lambda queued: queued.origin in {"agent", "task-watcher"})
        cancel_running_agents()
        clear_incomplete_tasks()

    async def run(self) -> None:
        """主处理循环：dequeue → 处理 → 检查后台 agent。"""
        state = self._state
        deps = self._deps
        console = deps.console

        while not state.exit_flag.is_set():
            # 1. 等待下一个命令
            cmd = await self._queue.dequeue(timeout=0.5, filter_fn=self._is_main_thread_command)
            if cmd is None:
                continue

            completed = True

            # 2. 按 mode 分发
            if cmd.mode in {"prompt", "slash_command"}:
                handler = self._handlers[cmd.mode]
                state.active_processing_task = asyncio.create_task(handler(cmd, deps))
                try:
                    await state.active_processing_task
                except asyncio.CancelledError:
                    completed = False
                    deps.ui.clear_status()
                    self._cleanup_interrupted_work()
                    logger.debug("processing interrupted: mode=%s", cmd.mode)
                finally:
                    state.active_processing_task = None
                    state.input_enabled.set()
            elif cmd.mode == "task_notification":
                notification_handler = self._handlers.get(cmd.mode)
                if notification_handler:
                    # 通知是同步处理（handler 内无 await 需求，但保持统一签名）
                    await notification_handler(cmd, deps)

            # 3. TaskListWatcher：enqueue LATER 优先级
            if cmd.mode == "prompt" and completed:
                from termpilot.tools.task import get_next_available_task, _save_tasks_to_disk
                next_task = get_next_available_task()
                if next_task:
                    next_task.owner = "main"
                    next_task.status = "in_progress"
                    _save_tasks_to_disk()
                    console.print(f"\n[dim]Auto-picking task #{next_task.id}: {next_task.subject}[/]")
                    self._queue.enqueue(QueuedCommand(
                        mode="prompt",
                        value=(
                            f"Continue with task #{next_task.id}: {next_task.subject}\n"
                            f"{next_task.description}"
                        ),
                        priority=Priority.LATER,
                        origin="task-watcher",
                    ))
