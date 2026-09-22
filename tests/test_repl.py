"""repl 子系统单元测试（P1-2 重构后各模块可独立测试）。"""

import asyncio

import pytest

from termpilot.queue import Priority, QueuedCommand, reset_main_queue
from termpilot.repl.loop import REPLLoop
from termpilot.repl.prompt_handler import (
    ReplDeps,
    assistant_appears_to_wait_for_user,
    queued_slash_name,
    should_defer_slash_for_user_reply,
)
from termpilot.repl.state import InteractiveState


class TestInteractiveState:
    def test_turn_lifecycle(self):
        state = InteractiveState()
        assert state.turn_generation == 0
        run_id = state.next_turn()
        assert run_id == 1
        assert state.is_current_turn(run_id)
        state.invalidate_current_turn()
        assert not state.is_current_turn(run_id)
        assert state.is_current_turn(2)

    def test_input_enabled_defaults_on(self):
        state = InteractiveState()
        assert state.input_enabled.is_set()
        assert not state.exit_flag.is_set()

    @pytest.mark.asyncio
    async def test_is_processing(self):
        state = InteractiveState()
        assert not state.is_processing  # None → not processing
        task = asyncio.create_task(asyncio.sleep(0.05))
        state.active_processing_task = task
        assert state.is_processing  # running → processing
        await task
        assert not state.is_processing  # done → not processing


class TestSlashDefer:
    def test_wait_detection_question(self):
        assert assistant_appears_to_wait_for_user("Which option do you prefer?")

    def test_wait_detection_plain(self):
        assert not assistant_appears_to_wait_for_user("Done. File created.")

    def test_queued_slash_name(self):
        cmd = QueuedCommand(mode="slash_command", value={"name": "Clear"}, priority=Priority.NEXT)
        assert queued_slash_name(cmd) == "clear"

    def test_defer_state_changing_when_awaiting_reply(self):
        cmd = QueuedCommand(
            mode="slash_command",
            value={"name": "clear", "args": "", "queued_during_active_turn": True},
            priority=Priority.NEXT,
        )
        assert should_defer_slash_for_user_reply(cmd, awaiting_user_reply=True)
        assert not should_defer_slash_for_user_reply(cmd, awaiting_user_reply=False)

    def test_no_defer_when_not_queued_during_turn(self):
        cmd = QueuedCommand(
            mode="slash_command",
            value={"name": "clear", "args": "", "queued_during_active_turn": False},
            priority=Priority.NEXT,
        )
        assert not should_defer_slash_for_user_reply(cmd, awaiting_user_reply=True)


class TestREPLLoop:
    def _make_deps(self, state, queue):
        return ReplDeps(
            console=None,
            ui=None,
            storage=None,
            tools=[],
            mcp_manager=None,
            cost_tracker=None,
            queue=queue,
            state=state,
            refresh_runtime=lambda: state.model,
            suspend_input=lambda: None,
        )

    def test_dispatches_prompt_to_registered_handler(self):
        from termpilot.queue import get_main_queue

        reset_main_queue()
        queue = get_main_queue()
        state = InteractiveState()
        deps = self._make_deps(state, queue)

        seen = []

        async def fake_prompt(cmd, deps):
            seen.append(cmd.value)
            state.exit_flag.set()

        loop = REPLLoop(state, queue, deps)
        loop.register("prompt", fake_prompt)
        queue.enqueue(QueuedCommand(mode="prompt", value="hello", priority=Priority.NEXT, origin="user"))

        asyncio.run(asyncio.wait_for(loop.run(), timeout=2))
        assert seen == ["hello"]

    def test_deferred_slash_not_dispatched(self):
        from termpilot.queue import get_main_queue

        reset_main_queue()
        queue = get_main_queue()
        state = InteractiveState()
        state.awaiting_user_reply = True
        deps = self._make_deps(state, queue)

        seen = []

        async def fake_slash(cmd, deps):
            seen.append(cmd.value)

        async def stop_after_grace(cmd, deps):
            state.exit_flag.set()

        loop = REPLLoop(state, queue, deps)
        loop.register("slash_command", fake_slash)
        loop.register("prompt", stop_after_grace)
        # 状态类命令在 awaiting_user_reply 期间应被过滤，不进主线程
        queue.enqueue(QueuedCommand(
            mode="slash_command",
            value={"name": "clear", "args": "", "queued_during_active_turn": True},
            priority=Priority.NEXT,
            origin="user",
        ))
        queue.enqueue(QueuedCommand(mode="prompt", value="stop", priority=Priority.NEXT, origin="user"))

        asyncio.run(asyncio.wait_for(loop.run(), timeout=2))
        assert seen == []  # clear 被延迟，未分发
