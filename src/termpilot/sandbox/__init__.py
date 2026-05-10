"""Sandbox public API.

This package is intentionally UI-agnostic so it can be extracted into a
standalone process isolation service later.
"""

from termpilot.sandbox.config import (
    SandboxConfig,
    SandboxFilesystemConfig,
    SandboxNetworkConfig,
    get_sandbox_config,
)
from termpilot.sandbox.manager import SandboxDecision, SandboxManager

__all__ = [
    "SandboxConfig",
    "SandboxFilesystemConfig",
    "SandboxNetworkConfig",
    "SandboxDecision",
    "SandboxManager",
    "get_sandbox_config",
]
