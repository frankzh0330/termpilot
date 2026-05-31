"""Apply trial workspace changes back to the source project."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig
from termpilot.workspace.diff import WorkspaceDiff, build_workspace_diff
from termpilot.workspace.fingerprint import file_fingerprint
from termpilot.workspace.manager import TrialWorkspace


@dataclass(frozen=True)
class WorkspaceConflict:
    path: str
    expected: str
    actual: str


class WorkspaceConflictError(RuntimeError):
    """Raised when the source project changed after trial workspace creation."""

    def __init__(self, conflicts: list[WorkspaceConflict]) -> None:
        self.conflicts = conflicts
        joined = ", ".join(conflict.path for conflict in conflicts[:5])
        suffix = "" if len(conflicts) <= 5 else f", +{len(conflicts) - 5} more"
        super().__init__(f"Source workspace changed since trial start: {joined}{suffix}")


def apply_workspace_changes(workspace: TrialWorkspace, config: TrialWorkspaceConfig) -> WorkspaceDiff:
    """Apply all changed files from a trial workspace back to source."""
    diff = build_workspace_diff(workspace, config)
    source_root = Path(workspace.source_cwd).expanduser().resolve()
    trial_root = Path(workspace.workspace_path).expanduser().resolve()
    _ensure_source_not_stale(workspace, source_root, diff)

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


def _ensure_source_not_stale(
        workspace: TrialWorkspace,
        source_root: Path,
        diff: WorkspaceDiff,
) -> None:
    baseline = workspace.metadata.get("source_fingerprints")
    if not isinstance(baseline, dict):
        return

    conflicts: list[WorkspaceConflict] = []
    for change in diff.changes:
        expected = str(baseline.get(change.path, "missing"))
        actual = file_fingerprint(source_root / change.path)
        if actual != expected:
            conflicts.append(WorkspaceConflict(path=change.path, expected=expected, actual=actual))
    if conflicts:
        raise WorkspaceConflictError(conflicts)
