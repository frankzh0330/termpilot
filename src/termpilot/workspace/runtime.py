"""Active trial workspace context.

This module is deliberately tiny: it gives tools and commands a shared runtime
context without binding the workspace core to CLI/session objects.
"""

from __future__ import annotations

from pathlib import Path

from termpilot.workspace.manager import TrialWorkspace


_active_workspace: TrialWorkspace | None = None


def set_active_trial_workspace(workspace: TrialWorkspace | None) -> None:
    """Set or clear the active trial workspace for this process."""
    global _active_workspace
    _active_workspace = workspace


def get_active_trial_workspace() -> TrialWorkspace | None:
    """Return the active trial workspace, if any."""
    return _active_workspace


def map_path_to_active_workspace(path: str | Path) -> Path:
    """Map a source path into the active trial workspace when applicable."""
    active = get_active_trial_workspace()
    raw_path = Path(path).expanduser()
    if active is None:
        return raw_path

    source_cwd = Path(active.source_cwd).expanduser().resolve()
    workspace_path = Path(active.workspace_path).expanduser().resolve()
    candidate = raw_path if raw_path.is_absolute() else source_cwd / raw_path
    try:
        resolved = candidate.resolve()
    except (OSError, ValueError):
        resolved = candidate.absolute()

    try:
        relative = resolved.relative_to(source_cwd)
    except ValueError:
        return raw_path
    return workspace_path / relative


def map_command_to_active_workspace(command: str) -> str:
    """Rewrite exact source-cwd path references in shell commands."""
    active = get_active_trial_workspace()
    if active is None:
        return command
    return command.replace(active.source_cwd, active.workspace_path)
