"""Diff helpers for trial workspaces."""

from __future__ import annotations

import difflib
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig
from termpilot.workspace.manager import METADATA_FILE, TrialWorkspace


MAX_DIFF_CHARS = 60_000
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
    ".gz", ".tar", ".pyc", ".so", ".dylib", ".dll", ".exe",
}


@dataclass(frozen=True)
class WorkspaceFileChange:
    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    binary: bool = False


@dataclass(frozen=True)
class WorkspaceDiff:
    workspace_id: str
    changes: list[WorkspaceFileChange] = field(default_factory=list)
    unified_diff: str = ""
    truncated: bool = False

    @property
    def changed_files(self) -> int:
        return len(self.changes)

    @property
    def additions(self) -> int:
        return sum(change.additions for change in self.changes)

    @property
    def deletions(self) -> int:
        return sum(change.deletions for change in self.changes)

    def summary(self) -> str:
        if not self.changes:
            return "No trial workspace changes."
        lines = [
            f"Trial workspace diff: {self.changed_files} files changed, "
            f"+{self.additions}/-{self.deletions}",
        ]
        for change in self.changes[:20]:
            marker = {
                "added": "A",
                "modified": "M",
                "deleted": "D",
            }.get(change.status, "?")
            suffix = " (binary)" if change.binary else f" (+{change.additions}/-{change.deletions})"
            lines.append(f"  {marker} {change.path}{suffix}")
        if len(self.changes) > 20:
            lines.append(f"  ... and {len(self.changes) - 20} more")
        if self.truncated:
            lines.append("  diff truncated")
        return "\n".join(lines)


def build_workspace_diff(workspace: TrialWorkspace, config: TrialWorkspaceConfig) -> WorkspaceDiff:
    source_root = Path(workspace.source_cwd).expanduser().resolve()
    trial_root = Path(workspace.workspace_path).expanduser().resolve()
    source_files = _collect_files(source_root, config)
    trial_files = _collect_files(trial_root, config)
    all_paths = sorted(source_files | trial_files)

    changes: list[WorkspaceFileChange] = []
    diff_parts: list[str] = []
    total_chars = 0
    truncated = False

    for rel_path in all_paths:
        source_file = source_root / rel_path
        trial_file = trial_root / rel_path
        if rel_path not in source_files:
            status = "added"
            change, diff_text = _diff_added(rel_path, trial_file)
        elif rel_path not in trial_files:
            status = "deleted"
            change, diff_text = _diff_deleted(rel_path, source_file)
        else:
            if _same_file(source_file, trial_file):
                continue
            status = "modified"
            change, diff_text = _diff_modified(rel_path, source_file, trial_file)
        changes.append(WorkspaceFileChange(path=rel_path, status=status, **change))
        if diff_text and not truncated:
            if total_chars + len(diff_text) > MAX_DIFF_CHARS:
                truncated = True
            else:
                diff_parts.append(diff_text)
                total_chars += len(diff_text)

    return WorkspaceDiff(
        workspace_id=workspace.id,
        changes=changes,
        unified_diff="\n".join(diff_parts),
        truncated=truncated,
    )


def _collect_files(root: Path, config: TrialWorkspaceConfig) -> set[str]:
    files: set[str] = set()
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_ignored(rel, config):
            continue
        files.add(rel)
    return files


def _is_ignored(rel_path: str, config: TrialWorkspaceConfig) -> bool:
    name = Path(rel_path).name
    if name == METADATA_FILE:
        return True
    parts = Path(rel_path).parts
    for pattern in config.copy_exclude_patterns:
        if pattern in parts or fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        return b"\0" in path.read_bytes()[:4096]
    except OSError:
        return True


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def _line_counts(lines: list[str]) -> tuple[int, int]:
    additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return additions, deletions


def _diff_added(rel_path: str, trial_file: Path) -> tuple[dict, str]:
    if _is_binary(trial_file):
        return {"additions": 0, "deletions": 0, "binary": True}, f"Binary file added: {rel_path}\n"
    lines = _read_lines(trial_file)
    diff_lines = list(difflib.unified_diff([], lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"))
    additions, deletions = _line_counts(diff_lines)
    return {"additions": additions, "deletions": deletions, "binary": False}, "".join(diff_lines)


def _diff_deleted(rel_path: str, source_file: Path) -> tuple[dict, str]:
    if _is_binary(source_file):
        return {"additions": 0, "deletions": 0, "binary": True}, f"Binary file deleted: {rel_path}\n"
    lines = _read_lines(source_file)
    diff_lines = list(difflib.unified_diff(lines, [], fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"))
    additions, deletions = _line_counts(diff_lines)
    return {"additions": additions, "deletions": deletions, "binary": False}, "".join(diff_lines)


def _diff_modified(rel_path: str, source_file: Path, trial_file: Path) -> tuple[dict, str]:
    if _is_binary(source_file) or _is_binary(trial_file):
        return {"additions": 0, "deletions": 0, "binary": True}, f"Binary file changed: {rel_path}\n"
    source_lines = _read_lines(source_file)
    trial_lines = _read_lines(trial_file)
    diff_lines = list(
        difflib.unified_diff(source_lines, trial_lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}")
    )
    additions, deletions = _line_counts(diff_lines)
    return {"additions": additions, "deletions": deletions, "binary": False}, "".join(diff_lines)
