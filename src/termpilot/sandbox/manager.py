"""Sandbox manager.

This module is the stable boundary BashTool uses. It returns explicit decisions
instead of directly consulting UI/session state, making future extraction easier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from termpilot.sandbox.base import SandboxAdapter
from termpilot.sandbox.config import SandboxConfig
from termpilot.sandbox.detect import detect_adapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxDecision:
    """Decision for a single command."""

    should_sandbox: bool
    reason: str = ""
    backend: str = ""


class SandboxManager:
    """Backend-agnostic sandbox orchestration."""

    _adapter: SandboxAdapter | None = None

    @classmethod
    def adapter(cls) -> SandboxAdapter | None:
        if cls._adapter is None:
            cls._adapter = detect_adapter()
        return cls._adapter

    @classmethod
    def decide(cls, command: str, config: SandboxConfig) -> SandboxDecision:
        """Determine whether a command should run inside a sandbox."""
        stripped = command.strip()
        if not config.enabled:
            return SandboxDecision(False, "sandbox disabled")
        if config.dangerously_disable:
            return SandboxDecision(False, "sandbox dangerously disabled")
        for prefix in config.excluded_commands:
            if stripped == prefix or stripped.startswith(prefix + " "):
                return SandboxDecision(False, f"excluded command: {prefix}")
        adapter = cls.adapter()
        if adapter is None or not adapter.is_available():
            return SandboxDecision(False, "no sandbox backend available")
        return SandboxDecision(True, "sandbox enabled", adapter.name)

    @classmethod
    def should_use_sandbox(cls, command: str, config: SandboxConfig) -> bool:
        return cls.decide(command, config).should_sandbox

    @classmethod
    def wrap_with_sandbox(cls, command: str, config: SandboxConfig, cwd: str) -> str:
        """Wrap a command with the selected sandbox backend."""
        adapter = cls.adapter()
        if adapter is None or not adapter.is_available():
            raise RuntimeError("Sandbox is enabled but no backend is available")
        return adapter.wrap_command(command, config, cwd)

    @classmethod
    def cleanup_after_command(cls, cwd: str | None = None) -> None:
        """Best-effort cleanup after a sandboxed command."""
        adapter = cls.adapter()
        if adapter:
            adapter.cleanup(str(Path(cwd or Path.cwd()).resolve()))
