"""Sandbox configuration loading.

The dataclasses in this module are plain policy objects. They avoid references
to CLI/UI/session state so this layer can later move into a separate service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from termpilot.config import get_settings


@dataclass
class SandboxFilesystemConfig:
    """Filesystem policy for sandboxed commands."""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    allow_read: list[str] = field(default_factory=lambda: ["**"])
    deny_read: list[str] = field(default_factory=list)


@dataclass
class SandboxNetworkConfig:
    """Network policy for sandboxed commands."""

    allow_domains: list[str] = field(default_factory=list)
    deny_domains: list[str] = field(default_factory=lambda: ["*"])
    allow_localhost: bool = False
    allow_unix_socket: bool = False


@dataclass
class SandboxConfig:
    """Top-level sandbox policy."""

    enabled: bool = False
    auto_allow_bash_if_sandboxed: bool = True
    dangerously_disable: bool = False
    excluded_commands: list[str] = field(default_factory=list)
    filesystem: SandboxFilesystemConfig = field(default_factory=SandboxFilesystemConfig)
    network: SandboxNetworkConfig = field(default_factory=SandboxNetworkConfig)


_PROTECTED_WRITE_PATTERNS = [
    "**/.git/**",
    "**/.env",
    "**/.termpilot/settings.json",
    "**/settings.json",
    "~/.ssh/**",
    "~/.gnupg/**",
]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _get_bool(raw: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key in raw:
            return bool(raw[key])
    return default


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def get_sandbox_config(cwd: str | None = None) -> SandboxConfig:
    """Load sandbox config from settings.json.

    Supported settings shape:
        {
          "sandbox": {
            "enabled": true,
            "autoAllowBashIfSandboxed": true,
            "dangerouslyDisableSandbox": false,
            "excludedCommands": ["git push"],
            "filesystem": {
              "allowWrite": ["<cwd>/**"],
              "denyWrite": ["**/.env"],
              "allowRead": ["**"],
              "denyRead": ["**/.ssh/**"]
            },
            "network": {
              "denyDomains": ["*"],
              "allowLocalhost": false
            }
          }
        }
    """
    settings = get_settings()
    raw = settings.get("sandbox", {})
    if not isinstance(raw, dict):
        raw = {}

    fs_raw = raw.get("filesystem", {})
    if not isinstance(fs_raw, dict):
        fs_raw = {}
    net_raw = raw.get("network", {})
    if not isinstance(net_raw, dict):
        net_raw = {}

    project_cwd = str(Path(cwd or Path.cwd()).resolve())
    allow_write = _as_list(fs_raw.get("allowWrite") or fs_raw.get("allow_write"))
    allow_write = [p.replace("<cwd>", project_cwd) for p in allow_write]
    if not allow_write:
        allow_write = [f"{project_cwd}/**"]

    deny_write = _as_list(fs_raw.get("denyWrite") or fs_raw.get("deny_write"))
    deny_write.extend(_PROTECTED_WRITE_PATTERNS)

    filesystem = SandboxFilesystemConfig(
        allow_write=_dedupe(allow_write),
        deny_write=_dedupe(deny_write),
        allow_read=_as_list(fs_raw.get("allowRead") or fs_raw.get("allow_read")) or ["**"],
        deny_read=_dedupe(_as_list(fs_raw.get("denyRead") or fs_raw.get("deny_read"))),
    )
    network = SandboxNetworkConfig(
        allow_domains=_as_list(net_raw.get("allowDomains") or net_raw.get("allow_domains")),
        deny_domains=_as_list(net_raw.get("denyDomains") or net_raw.get("deny_domains")) or ["*"],
        allow_localhost=_get_bool(net_raw, "allowLocalhost", "allow_localhost", default=False),
        allow_unix_socket=_get_bool(net_raw, "allowUnixSocket", "allow_unix_socket", default=False),
    )
    return SandboxConfig(
        enabled=_get_bool(raw, "enabled", default=False),
        auto_allow_bash_if_sandboxed=_get_bool(
            raw,
            "autoAllowBashIfSandboxed",
            "auto_allow_bash_if_sandboxed",
            default=True,
        ),
        dangerously_disable=_get_bool(
            raw,
            "dangerouslyDisableSandbox",
            "dangerously_disable",
            default=False,
        ),
        excluded_commands=_as_list(raw.get("excludedCommands") or raw.get("excluded_commands")),
        filesystem=filesystem,
        network=network,
    )
