"""Portable copy backend for trial workspaces."""

from __future__ import annotations

import shutil
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig


class CopyWorkspaceBackend:
    """Create a workspace with shutil.copytree."""

    name = "copy"

    def is_available(self, source_cwd: Path) -> bool:
        return source_cwd.is_dir()

    def create(self, source_cwd: Path, workspace_path: Path, config: TrialWorkspaceConfig) -> None:
        if workspace_path.exists():
            raise FileExistsError(f"Trial workspace already exists: {workspace_path}")
        ignore = shutil.ignore_patterns(*config.copy_exclude_patterns)
        shutil.copytree(source_cwd, workspace_path, ignore=ignore, symlinks=True)

    def discard(self, workspace_path: Path) -> None:
        shutil.rmtree(workspace_path, ignore_errors=True)
