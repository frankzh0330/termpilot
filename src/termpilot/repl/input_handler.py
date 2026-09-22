"""用户输入收集（从 cli.py 的 _input_collector / _suspend_prompt_input 提取）。

InputHandler 只负责收集输入并入队（Observer 模式：向 MessageQueue 发事件），
不直接修改会话状态；处理统一由 repl.loop.REPLLoop 串行完成。
"""

from __future__ import annotations

import logging
from typing import Any

from prompt_toolkit.patch_stdout import patch_stdout

from termpilot.commands import parse_slash_command
from termpilot.queue import Priority, QueuedCommand
from termpilot.repl.state import InteractiveState

logger = logging.getLogger(__name__)


class InputHandler:
    """收集用户输入：prompt_toolkit 会话 → MessageQueue。"""

    def __init__(self, pt_session: Any, queue: Any, state: InteractiveState, console: Any):
        self._session = pt_session
        self._queue = queue
        self._state = state
        self._console = console

    def suspend(self) -> None:
        """Temporarily stop the main prompt so interactive tools can read stdin."""
        self._state.input_enabled.clear()
        try:
            app = self._session.app
            if getattr(app, "is_running", False):
                app.exit(result="")
        except Exception as exc:
            logger.debug("failed to suspend prompt input: %s", exc)

    async def collect_loop(self) -> None:
        """收集用户输入，只负责入队，不直接修改会话状态。"""
        while not self._state.exit_flag.is_set():
            try:
                await self._state.input_enabled.wait()
                with patch_stdout(raw=True):
                    user_input = await self._session.prompt_async()

                user_input = user_input.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")

                if not user_input.strip():
                    continue

                # ── Slash 命令：入队，由 drain loop 串行处理 ──
                parsed = parse_slash_command(user_input)
                if parsed:
                    cmd_name, cmd_args = parsed
                    queued_during_active_turn = self._state.is_processing
                    self._queue.enqueue(QueuedCommand(
                        mode="slash_command",
                        value={
                            "name": cmd_name,
                            "args": cmd_args,
                            "queued_during_active_turn": queued_during_active_turn,
                        },
                        priority=Priority.NEXT,
                        origin="user",
                    ))
                    continue

                # ── 普通输入：入队 ──
                self._queue.enqueue(QueuedCommand(
                    mode="prompt",
                    value=user_input,
                    priority=Priority.NEXT,
                    origin="user",
                ))

            except KeyboardInterrupt:
                self._console.print("\n[dim]再见！[/]")
                self._state.exit_flag.set()
                return
