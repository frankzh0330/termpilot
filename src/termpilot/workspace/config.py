"""Trial workspace configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from termpilot.config import get_settings


DEFAULT_EXCLUDE_PATTERNS = [
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "*.egg-info",
]


@dataclass(frozen=True)
class TrialWorkspaceConfig:
    """Policy for creating isolated trial workspaces."""

    enabled: bool = False
    backend: str = "auto"
    root: str = "~/.termpilot/trial-workspaces"
    keep_failed: bool = True
    ttl_hours: int = 24
    prefer_git_worktree: bool = True
    copy_exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATTERNS))

    @property
    def root_path(self) -> Path:
        return Path(self.root).expanduser()


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


def _get_int(raw: dict[str, Any], *keys: str, default: int) -> int:
    for key in keys:
        if key in raw:
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                return default
    return default


def get_trial_workspace_config() -> TrialWorkspaceConfig:
    """Load trial workspace config from settings.json.

    Supported settings shape:
        {
          "trialWorkspace": {
            "enabled": true,
            "backend": "auto",
            "root": "~/.termpilot/trial-workspaces",
            "preferGitWorktree": true
          }
        }
    """
    settings = get_settings()
    raw = settings.get("trialWorkspace") or settings.get("trial_workspace") or {}
    if not isinstance(raw, dict):
        raw = {}

    exclude_patterns = _as_list(
        raw.get("copyExcludePatterns") or raw.get("copy_exclude_patterns")
    )
    if not exclude_patterns:
        exclude_patterns = list(DEFAULT_EXCLUDE_PATTERNS)

    return TrialWorkspaceConfig(
        enabled=_get_bool(raw, "enabled", default=False),
        backend=str(raw.get("backend") or "auto"),
        root=str(raw.get("root") or "~/.termpilot/trial-workspaces"),
        keep_failed=_get_bool(raw, "keepFailed", "keep_failed", default=True),
        ttl_hours=_get_int(raw, "ttlHours", "ttl_hours", default=24),
        prefer_git_worktree=_get_bool(
            raw,
            "preferGitWorktree",
            "prefer_git_worktree",
            default=True,
        ),
        copy_exclude_patterns=exclude_patterns,
    )
