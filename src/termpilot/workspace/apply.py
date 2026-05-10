"""Apply trial workspace changes back to the source project."""

from __future__ import annotations

import shutil
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig
from termpilot.workspace.diff import WorkspaceDiff, build_workspace_diff
from termpilot.workspace.manager import TrialWorkspace


def apply_workspace_changes(workspace: TrialWorkspace, config: TrialWorkspaceConfig) -> WorkspaceDiff:
    """Apply all changed files from a trial workspace back to source."""
    diff = build_workspace_diff(workspace, config)
    source_root = Path(workspace.source_cwd).expanduser().resolve()
    trial_root = Path(workspace.workspace_path).expanduser().resolve()

    for change in diff.changes:
        source_path = source_root / change.path
        trial_path = trial_root / change.path
        if change.status == "deleted":
            if source_path.exists():
                source_path.unlink()
            continue
        source_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(trial_path, source_path)

    return diff
