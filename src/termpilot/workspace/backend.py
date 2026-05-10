"""Backend contract for trial workspace creation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from termpilot.workspace.config import TrialWorkspaceConfig


class WorkspaceBackend(Protocol):
    """Backend that materializes a source project into an isolated workspace."""

    name: str

    def is_available(self, source_cwd: Path) -> bool:
        """Return whether this backend can create a workspace for source_cwd."""

    def create(self, source_cwd: Path, workspace_path: Path, config: TrialWorkspaceConfig) -> None:
        """Create workspace_path from source_cwd."""

    def discard(self, workspace_path: Path) -> None:
        """Discard workspace_path and any backend-specific metadata."""
