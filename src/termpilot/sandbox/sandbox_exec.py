"""macOS sandbox-exec adapter."""

from __future__ import annotations

import shlex
import shutil

from termpilot.sandbox.base import SandboxAdapter
from termpilot.sandbox.config import SandboxConfig


class SandboxExecAdapter(SandboxAdapter):
    """Wrap commands with macOS sandbox-exec."""

    name = "sandbox-exec"

    def is_available(self) -> bool:
        return shutil.which("sandbox-exec") is not None

    def wrap_command(self, command: str, config: SandboxConfig, cwd: str) -> str:
        profile = self._build_profile(config, cwd)
        args = ["sandbox-exec", "-p", profile, "--", "/bin/bash", "-lc", command]
        return " ".join(shlex.quote(arg) for arg in args)

    def _build_profile(self, config: SandboxConfig, cwd: str) -> str:
        lines = [
            "(version 1)",
            "(allow default)",
            "(allow file-read*)",
            f'(allow file-write* (subpath "{cwd}"))',
            '(allow file-write* (subpath "/tmp"))',
            '(allow file-write* (subpath "/private/tmp"))',
            '(deny file-write* (regex #"/\\.git(/|$)"))',
            '(deny file-write* (regex #"/\\.ssh(/|$)"))',
            '(deny file-write* (regex #"/\\.gnupg(/|$)"))',
            '(deny file-write* (regex #"/\\.termpilot/settings\\.json$"))',
            '(deny file-write* (regex #"/\\.env$"))',
        ]
        if "*" in config.network.deny_domains and not config.network.allow_domains:
            lines.append("(deny network*)")
            if config.network.allow_localhost:
                lines.extend([
                    '(allow network-outbound (remote ip "127.0.0.1:*"))',
                    '(allow network-outbound (remote ip "::1:*"))',
                ])
        return "\n".join(lines)
