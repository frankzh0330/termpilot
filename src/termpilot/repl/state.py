"""REPL 共享可变状态。

替代原先散落在 _async_interactive 各嵌套闭包里的 nonlocal 变量
（messages / title_generated / awaiting_user_reply / active_processing_task /
turn_generation / client / model / system_prompt ...），
让状态变更集中在一个可追踪的 dataclass 上。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from termpilot.permissions import PermissionContext


@dataclass
class InteractiveState:
    """一次交互会话的全部可变状态。

    生命周期：_async_interactive 创建 → 各 handler 读写 → 退出后丢弃。
    permission_context 是可变对象（cycle mode 只改 .mode 属性，不 rebind），
    client/model/system_prompt 会被 refresh_runtime（/model 命令）整体替换。
    """

    # 会话消息（同一 list 对象贯穿全程，commands.py 的命令直接修改它）
    messages: list[dict[str, Any]] = field(default_factory=list)

    # 首轮对话后生成会话标题
    title_generated: bool = False
    # 上一轮 assistant 回复像在等用户确认（延迟状态类 slash 命令）
    awaiting_user_reply: bool = False
    # 当前正在处理的 prompt/slash 任务（用于 Esc 中断）
    active_processing_task: asyncio.Task[None] | None = None

    # turn 代数：中断后旧 turn 的回调（流式渲染/标题生成）凭此作废
    turn_generation: int = 0

    # 运行时（/model 后由 refresh_runtime 替换）
    client: Any = None
    client_format: str = "openai"
    model: str = ""
    system_prompt: str = ""

    permission_context: PermissionContext = None  # type: ignore[assignment]

    # 输入开关：交互式工具读 stdin 时暂停主 prompt
    input_enabled: asyncio.Event = field(default_factory=asyncio.Event)
    # 退出信号
    exit_flag: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.input_enabled.set()

    # ── turn 管理 ──────────────────────────────────────────────

    def next_turn(self) -> int:
        """开启新 turn，返回该 turn 的代数 id。"""
        self.turn_generation += 1
        return self.turn_generation

    def invalidate_current_turn(self) -> None:
        """作废当前 turn（中断时调用），旧回调凭 run_id 失效。"""
        self.turn_generation += 1

    def is_current_turn(self, run_id: int) -> bool:
        return run_id == self.turn_generation

    # ── 处理中任务 ─────────────────────────────────────────────

    @property
    def is_processing(self) -> bool:
        return self.active_processing_task is not None and not self.active_processing_task.done()
