"""Git worktree backend for large repositories."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig


class GitWorktreeBackend:
    """Create a trial workspace using `git worktree add --detach`."""

    name = "git-worktree"

    def is_available(self, source_cwd: Path) -> bool:
        if shutil.which("git") is None:
            return False
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=source_cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    def create(self, source_cwd: Path, workspace_path: Path, config: TrialWorkspaceConfig) -> None:
        if workspace_path.exists():
            raise FileExistsError(f"Trial workspace already exists: {workspace_path}")
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(workspace_path), "HEAD"],
            cwd=source_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git worktree failed"
            raise RuntimeError(message)

    def discard(self, workspace_path: Path) -> None:
        if not workspace_path.exists():
            return
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(workspace_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            shutil.rmtree(workspace_path, ignore_errors=True)
