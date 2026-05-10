"""Linux bubblewrap sandbox adapter."""

from __future__ import annotations

import shlex
import shutil

from termpilot.sandbox.base import SandboxAdapter
from termpilot.sandbox.config import SandboxConfig


class BubblewrapAdapter(SandboxAdapter):
    """Wrap commands with bubblewrap on Linux."""

    name = "bubblewrap"

    def is_available(self) -> bool:
        return shutil.which("bwrap") is not None

    def wrap_command(self, command: str, config: SandboxConfig, cwd: str) -> str:
        args = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--bind", cwd, cwd,
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--die-with-parent",
            "--new-session",
            "--chdir", cwd,
        ]
        if "*" in config.network.deny_domains and not config.network.allow_domains:
            args.append("--unshare-net")
        args.extend(["--", "/bin/bash", "-lc", command])
        return " ".join(shlex.quote(arg) for arg in args)
