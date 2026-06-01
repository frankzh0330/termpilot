"""Trial workspace manager.

The manager exposes a small service-like API. CLI commands and future agent
runtime code should depend on this boundary instead of constructing workspaces
directly.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from termpilot.workspace.backend import WorkspaceBackend
from termpilot.workspace.config import TrialWorkspaceConfig, get_trial_workspace_config
from termpilot.workspace.copy_backend import CopyWorkspaceBackend
from termpilot.workspace.git_backend import GitWorktreeBackend


METADATA_FILE = ".termpilot-trial.json"


@dataclass(frozen=True)
class TrialWorkspace:
    """Metadata for one isolated trial workspace."""

    id: str
    source_cwd: str
    workspace_path: str
    backend: str
    state: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    purpose: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.workspace_path)


class TrialWorkspaceManager:
    """Create, inspect, and discard trial workspaces."""

    def __init__(self, config: TrialWorkspaceConfig | None = None) -> None:
        self.config = config or get_trial_workspace_config()
        self._copy_backend = CopyWorkspaceBackend()
        self._git_backend = GitWorktreeBackend()

    def create(
        self,
        source_cwd: str | Path | None = None,
        *,
        purpose: str = "",
        backend: str | None = None,
    ) -> TrialWorkspace:
        """Create a new trial workspace."""
        source_path = Path(source_cwd or Path.cwd()).expanduser().resolve()
        if not source_path.is_dir():
            raise NotADirectoryError(f"Source cwd is not a directory: {source_path}")

        workspace_id = self._new_id()
        root = self._root()
        workspace_path = root / workspace_id
        self._ensure_workspace_outside_source(source_path, workspace_path)
        selected = self._select_backend(source_path, backend)
        selected.create(source_path, workspace_path, self.config)
        baseline = self._build_baseline(source_path)

        workspace = TrialWorkspace(
            id=workspace_id,
            source_cwd=str(source_path),
            workspace_path=str(workspace_path),
            backend=selected.name,
            purpose=purpose,
            metadata={"source_fingerprints": baseline},
        )
        self._write_metadata(workspace)
        return workspace

    def get(self, workspace_id: str) -> TrialWorkspace | None:
        """Read workspace metadata by id."""
        path = self._root() / workspace_id / METADATA_FILE
        if not path.exists():
            return None
        return self._read_metadata(path)

    def list(self) -> list[TrialWorkspace]:
        """List known trial workspaces under the configured root."""
        root = self._root()
        if not root.exists():
            return []
        workspaces: list[TrialWorkspace] = []
        for metadata_path in sorted(root.glob(f"*/{METADATA_FILE}")):
            try:
                workspaces.append(self._read_metadata(metadata_path))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return workspaces

    def discard(self, workspace_id: str) -> bool:
        """Discard a workspace. Returns False when the id does not exist."""
        workspace = self.get(workspace_id)
        if workspace is None:
            return False
        workspace_path = Path(workspace.workspace_path).expanduser().resolve()
        self._ensure_under_root(workspace_path)
        backend = self._backend_by_name(workspace.backend)
        backend.discard(workspace_path)
        if workspace_path.exists():
            shutil.rmtree(workspace_path, ignore_errors=True)
        return True

    def mark_state(self, workspace_id: str, state: str, **metadata_updates: Any) -> TrialWorkspace | None:
        """Update workspace lifecycle state and metadata."""
        workspace = self.get(workspace_id)
        if workspace is None:
            return None
        metadata = dict(workspace.metadata)
        metadata.update(metadata_updates)
        updated = replace(
            workspace,
            state=state,
            updated_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )
        self._write_metadata(updated)
        return updated

    def cleanup_stale(self, *, include_active: bool = False) -> list[str]:
        """Remove workspaces older than ttl_hours.

        Active workspaces are preserved by default. This keeps manual work safe
        while still allowing old applied, stopped, or failed workspaces to age out.
        """
        ttl = max(0, int(self.config.ttl_hours))
        if ttl <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
        removed: list[str] = []
        for workspace in self.list():
            if workspace.state == "active" and not include_active:
                continue
            created = self._parse_datetime(workspace.created_at)
            if created and created < cutoff and self.discard(workspace.id):
                removed.append(workspace.id)
        return removed

    def diff(self, workspace_id: str):
        """Return a diff object for a workspace."""
        from termpilot.workspace.diff import build_workspace_diff

        workspace = self.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Unknown trial workspace: {workspace_id}")
        return build_workspace_diff(workspace, self.config)

    def apply(self, workspace_id: str):
        """Apply workspace changes back to the source project."""
        from termpilot.workspace.apply import apply_workspace_changes

        workspace = self.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Unknown trial workspace: {workspace_id}")
        diff = apply_workspace_changes(workspace, self.config)
        self.mark_state(
            workspace_id,
            "applied",
            applied_at=datetime.now(timezone.utc).isoformat(),
            applied_files=[change.path for change in diff.changes],
        )
        return diff

    def _select_backend(self, source_cwd: Path, backend: str | None = None) -> WorkspaceBackend:
        requested = (backend or self.config.backend or "auto").strip().lower()
        if requested in {"git", "git-worktree", "worktree"}:
            if not self._git_backend.is_available(source_cwd):
                raise RuntimeError("git worktree backend is not available for this source")
            return self._git_backend
        if requested == "copy":
            return self._copy_backend
        if requested != "auto":
            raise ValueError(f"Unknown trial workspace backend: {requested}")
        if self.config.prefer_git_worktree and self._git_backend.is_available(source_cwd):
            return self._git_backend
        return self._copy_backend

    def _backend_by_name(self, name: str) -> WorkspaceBackend:
        if name == self._git_backend.name:
            return self._git_backend
        return self._copy_backend

    def _root(self) -> Path:
        root = self.config.root_path.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _ensure_under_root(self, workspace_path: Path) -> None:
        root = self._root()
        if not workspace_path.is_relative_to(root):
            raise ValueError(f"Refusing to discard path outside trial root: {workspace_path}")

    def _ensure_workspace_outside_source(self, source_cwd: Path, workspace_path: Path) -> None:
        if workspace_path.is_relative_to(source_cwd):
            raise ValueError(
                "Trial workspace root must be outside the source project to avoid recursive copies"
            )

    def _write_metadata(self, workspace: TrialWorkspace) -> None:
        path = Path(workspace.workspace_path) / METADATA_FILE
        path.write_text(json.dumps(asdict(workspace), ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_metadata(self, metadata_path: Path) -> TrialWorkspace:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Invalid trial workspace metadata")
        return TrialWorkspace(
            id=str(raw["id"]),
            source_cwd=str(raw["source_cwd"]),
            workspace_path=str(raw["workspace_path"]),
            backend=str(raw["backend"]),
            state=str(raw.get("state") or "active"),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or raw.get("created_at") or ""),
            purpose=str(raw.get("purpose") or ""),
            metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        )

    def _new_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"tw-{timestamp}-{uuid.uuid4().hex[:8]}"

    def _build_baseline(self, source_path: Path) -> dict[str, str]:
        from termpilot.workspace.fingerprint import build_source_fingerprints

        return build_source_fingerprints(source_path, self.config)

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            return None
