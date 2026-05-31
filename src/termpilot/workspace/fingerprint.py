"""Workspace source fingerprint helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from termpilot.workspace.config import TrialWorkspaceConfig
from termpilot.workspace.diff import _collect_files


def build_source_fingerprints(source_root: Path, config: TrialWorkspaceConfig) -> dict[str, str]:
    """Build content fingerprints for files visible to trial workspace diffing."""

    root = source_root.expanduser().resolve()
    fingerprints: dict[str, str] = {}
    for rel_path in _collect_files(root, config):
        path = root / rel_path
        fingerprints[rel_path] = file_fingerprint(path)
    return fingerprints


def file_fingerprint(path: Path) -> str:
    """Return a stable fingerprint for one file path."""

    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"file:{stat.st_size}:{digest}"
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return f"error:{type(exc).__name__}"
