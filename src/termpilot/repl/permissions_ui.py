"""权限确认的终端交互 UI（从 cli.py 提取）。"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console

from termpilot.permissions import PermissionBehavior, PermissionResult
from termpilot.ui import QuietUI

console = Console()


def permission_result_from_choice(tool_name: str, choice: Any) -> PermissionResult:
    """Map permission menu output to a permission result."""
    if isinstance(choice, str):
        normalized_choice = choice.strip().lower()
        if normalized_choice.startswith("allow once"):
            choice = "allow_once"
        elif normalized_choice.startswith("always allow"):
            choice = "always_allow"
        elif normalized_choice.startswith("always deny"):
            choice = "always_deny"
        elif normalized_choice.startswith("deny"):
            choice = "deny"

    if choice in ("allow_once", "1"):
        return PermissionResult(behavior=PermissionBehavior.ALLOW)

    if choice in ("always_allow", "2"):
        return PermissionResult(
            behavior=PermissionBehavior.ALLOW,
            rule_updates=[{
                "tool_name": tool_name,
                "pattern": "*",
                "behavior": "allow",
            }],
        )

    if choice in ("deny", "3"):
        return PermissionResult(
            behavior=PermissionBehavior.DENY,
            message="用户拒绝",
        )

    if choice in ("always_deny", "4"):
        return PermissionResult(
            behavior=PermissionBehavior.DENY,
            message="用户拒绝",
            rule_updates=[{
                "tool_name": tool_name,
                "pattern": "*",
                "behavior": "deny",
            }],
        )

    # Be conservative, but do not persist a deny rule for cancelled/unknown output.
    return PermissionResult(
        behavior=PermissionBehavior.DENY,
        message="用户取消或未选择",
    )


def ask_permission_choice() -> str | None:
    """Ask for permission using stable numeric input."""
    console.print("[bold]选择操作[/]")
    console.print("  [1] Allow once    (本次允许)")
    console.print("  [2] Always allow  (始终允许同类操作)")
    console.print("  [3] Deny          (拒绝)")
    console.print("  [4] Always deny   (始终拒绝同类操作)")
    console.print()
    try:
        return input("选择 [1-4]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return None


async def permission_prompt(
        tool_name: str,
        tool_input: dict,
        message: str,
        ui: QuietUI | None = None,
) -> PermissionResult:
    """权限确认提示。对应 TS useCanUseTool.tsx 的用户交互部分。"""
    if ui:
        ui.clear_status()
    console.print()
    console.rule("[bold yellow]权限请求[/]")
    console.print(f"[bold]{tool_name}[/] — {message}")

    # 显示操作摘要
    if tool_name == "bash":
        cmd = tool_input.get("command", "")
        console.print(f"  [dim]命令:[/] {cmd[:200]}")
    elif tool_name in ("write_file", "edit_file"):
        console.print(f"  [dim]文件:[/] {tool_input.get('file_path', '')}")

    console.print()

    try:
        loop = asyncio.get_event_loop()
        choice = await loop.run_in_executor(
            None,
            ask_permission_choice,
        )
    except (KeyboardInterrupt, EOFError):
        choice = None

    return permission_result_from_choice(tool_name, choice)
