"""Sandbox adapter abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from termpilot.sandbox.config import SandboxConfig


class SandboxAdapter(ABC):
    """Platform adapter that transforms commands into sandboxed commands."""

    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether the platform backend is available."""

    @abstractmethod
    def wrap_command(self, command: str, config: SandboxConfig, cwd: str) -> str:
        """Transform a shell command into a sandboxed command."""

    def cleanup(self, cwd: str) -> None:
        """Cleanup after command execution."""
        return None
