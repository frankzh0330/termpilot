"""Shell 命令执行工具。

对应 TS: tools/BashTool/BashTool.tsx
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_INLINE_OUTPUT = 30_000
MAX_INLINE_LINES = 500
MAX_TIMEOUT_MS = 600_000


@dataclass
class BashResult:
    """Raw shell execution result."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def classify_command(command: str) -> str:
    """Classify a shell command for future routing/policy decisions."""
    try:
        parts = shlex.split(command.strip(), posix=True) if command.strip() else []
    except ValueError:
        parts = command.strip().split()
    first_cmd = parts[0] if parts else ""
    categories = {
        "read": {"cat", "head", "tail", "less", "more", "file", "stat", "wc"},
        "search": {"grep", "rg", "ag", "ack", "find", "fd"},
        "list": {"ls", "tree", "du", "df"},
        "write": {"rm", "mv", "cp", "mkdir", "touch", "chmod", "chown", "tee", "truncate", "install"},
        "admin": {"sudo", "systemctl", "docker", "pip", "npm", "apt", "yum", "brew"},
        "network": {"curl", "wget", "ssh", "scp", "rsync", "nc"},
    }
    for category, commands in categories.items():
        if first_cmd in commands:
            return category
    return "unknown"


class BashTool:
    """执行 shell 命令并返回输出。

    is_concurrency_safe=False：bash 命令可能有副作用。
    TS 版中通过 isReadOnly(input) 判断，Python 简化版默认 False。
    """

    _cwd: str = ""

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Executes a given bash command and returns its output.\n"
            "\n"
            "The working directory persists between commands, but shell state does not. "
            "The shell environment is initialized from the user's profile (bash or zsh).\n"
            "\n"
            "IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`, `tail`, `sed`, "
            "`awk`, or `echo` commands, unless explicitly instructed or after you have verified that "
            "a dedicated tool cannot accomplish your task. Instead, use the appropriate dedicated tool:\n"
            " - Directory summary: Use list_dir (NOT ls, find, or tree)\n"
            " - File search: Use Glob (NOT find or ls)\n"
            " - Content search: Use Grep (NOT grep or rg)\n"
            " - Read files: Use Read (NOT cat/head/tail)\n"
            " - Edit files: Use Edit (NOT sed/awk)\n"
            " - Write files: Use Write (NOT echo/cat <<EOF)\n"
            " - Communication: Output text directly (NOT echo/printf)\n"
            "\n"
            "Instructions:\n"
            "- Always quote file paths that contain spaces with double quotes\n"
            "- You may specify an optional timeout in milliseconds (up to 600000ms / 10 minutes). "
            "By default, your command will timeout after 120000ms (2 minutes).\n"
            "- When issuing multiple commands: if independent, make separate calls in parallel; "
            "if dependent, use && to chain them.\n"
            "- For git commands: prefer creating a new commit over amending. "
            "Before destructive operations, consider safer alternatives."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（毫秒），默认 120000（2 分钟）",
                },
            },
            "required": ["command"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    async def call(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        timeout_ms = min(int(kwargs.get("timeout") or 120000), MAX_TIMEOUT_MS)
        on_progress = kwargs.get("_on_progress")

        if not command.strip():
            return "错误：命令为空"

        cwd = self._resolve_cwd()
        sandboxed = False
        from termpilot.workspace import map_command_to_active_workspace
        effective_command = map_command_to_active_workspace(command)
        try:
            from termpilot.sandbox import SandboxManager, get_sandbox_config

            sandbox_config = get_sandbox_config(cwd)
            if SandboxManager.should_use_sandbox(command, sandbox_config):
                effective_command = SandboxManager.wrap_with_sandbox(command, sandbox_config, cwd)
                sandboxed = True
        except Exception as exc:
            return f"错误：sandbox 初始化失败: {exc}"

        try:
            result = await self._execute(
                effective_command,
                cwd,
                timeout_ms,
                on_progress=on_progress,
            )
            if sandboxed:
                from termpilot.sandbox import SandboxManager

                SandboxManager.cleanup_after_command(cwd)
        finally:
            pass

        if not result.timed_out and result.exit_code == 0:
            self._update_cwd(command, cwd)
        return self._process_output(command, result, sandboxed=sandboxed)

    def _resolve_cwd(self) -> str:
        from termpilot.workspace import get_active_trial_workspace
        active_workspace = get_active_trial_workspace()
        if active_workspace is not None:
            return active_workspace.workspace_path

        cwd = self._cwd or str(Path.cwd())
        try:
            path = Path(cwd).expanduser().resolve()
            if path.is_dir():
                return str(path)
        except (OSError, ValueError):
            pass
        self.__class__._cwd = str(Path.cwd())
        return self.__class__._cwd

    def _update_cwd(self, command: str, prev_cwd: str) -> None:
        stripped = command.strip()
        if not stripped.startswith("cd "):
            return
        target = stripped[3:].strip()
        if "&&" in target or ";" in target or "|" in target:
            return
        target = target.strip("'\"")
        if not target:
            return
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = Path(prev_cwd) / path
        try:
            resolved = path.resolve()
            if resolved.is_dir():
                self.__class__._cwd = str(resolved)
        except (OSError, ValueError):
            return

    async def _execute(
            self,
            command: str,
            cwd: str,
            timeout_ms: int,
            on_progress: Any = None,
    ) -> BashResult:
        timeout_sec = timeout_ms / 1000
        proc: asyncio.subprocess.Process | None = None
        try:
            if on_progress:
                on_progress({"type": "progress", "status": "running", "command": command})
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            return BashResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode if proc.returncode is not None else -1,
            )
        except asyncio.TimeoutError:
            if proc:
                await self._kill_process_tree(proc)
            return BashResult(
                stdout="",
                stderr=f"Timeout after {timeout_sec:.1f}s",
                exit_code=-9,
                timed_out=True,
            )
        except Exception as exc:
            return BashResult(stdout="", stderr=str(exc), exit_code=-1)

    async def _kill_process_tree(self, proc: asyncio.subprocess.Process) -> None:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            await asyncio.sleep(0.3)
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except (ProcessLookupError, PermissionError, AttributeError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    def _format_raw(self, result: BashResult) -> str:
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout)
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr}")
        if result.exit_code != 0:
            parts.append(f"[exit code: {result.exit_code}]")
        return "\n".join(parts) if parts else f"[exit code: {result.exit_code}]"

    def _process_output(self, command: str, result: BashResult, *, sandboxed: bool) -> str:
        raw = self._format_raw(result)
        line_count = raw.count("\n") + 1
        if len(raw) <= MAX_INLINE_OUTPUT and line_count <= MAX_INLINE_LINES:
            if sandboxed:
                return f"[sandboxed]\n{raw}"
            return raw

        preview = raw[:2000]
        header = (
            f"[Output too large: {len(raw):,} chars, {line_count:,} lines]\n"
            f"[Command: {command[:200]}]\n"
        )
        if sandboxed:
            header += "[sandboxed]\n"
        return f"{header}\n--- First 2000 chars ---\n{preview}\n--- End preview ---"
