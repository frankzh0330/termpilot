"""Sandbox backend detection."""

from __future__ import annotations

import platform

from termpilot.sandbox.base import SandboxAdapter
from termpilot.sandbox.bubblewrap import BubblewrapAdapter
from termpilot.sandbox.sandbox_exec import SandboxExecAdapter


def detect_adapter() -> SandboxAdapter | None:
    """Return the best available sandbox adapter for this host."""
    system = platform.system().lower()
    candidates: list[SandboxAdapter] = []
    if system == "linux":
        candidates.append(BubblewrapAdapter())
    elif system == "darwin":
        candidates.append(SandboxExecAdapter())

    for adapter in candidates:
        if adapter.is_available():
            return adapter
    return None
