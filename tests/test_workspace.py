"""Trial workspace tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from termpilot.workspace import TrialWorkspaceConfig, TrialWorkspaceManager, get_trial_workspace_config
from termpilot.workspace.runtime import (
    get_active_trial_workspace,
    map_path_to_active_workspace,
    set_active_trial_workspace,
)


def test_trial_workspace_config_defaults(tmp_settings, env_clean):
    config = get_trial_workspace_config()

    assert config.enabled is False
    assert config.backend == "auto"
    assert config.prefer_git_worktree is True
    assert ".git" in config.copy_exclude_patterns


def test_trial_workspace_config_loads_settings(tmp_settings, env_clean):
    tmp_settings({
        "trialWorkspace": {
            "enabled": True,
            "backend": "copy",
            "root": "/tmp/termpilot-trials",
            "keepFailed": False,
            "ttlHours": 6,
            "preferGitWorktree": False,
            "copyExcludePatterns": [".git", "node_modules"],
        }
    })

    config = get_trial_workspace_config()

    assert config.enabled is True
    assert config.backend == "copy"
    assert config.root == "/tmp/termpilot-trials"
    assert config.keep_failed is False
    assert config.ttl_hours == 6
    assert config.prefer_git_worktree is False
    assert config.copy_exclude_patterns == [".git", "node_modules"]


def test_create_copy_workspace_writes_metadata_and_copies_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("ignored\n", encoding="utf-8")
    root = tmp_path / "trials"
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(root), backend="copy", prefer_git_worktree=False)
    )

    workspace = manager.create(source, purpose="test copy")

    workspace_path = Path(workspace.workspace_path)
    assert workspace.backend == "copy"
    assert workspace.purpose == "test copy"
    assert (workspace_path / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert not (workspace_path / ".git").exists()
    assert (workspace_path / ".termpilot-trial.json").exists()


def test_list_and_get_workspaces(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(tmp_path / "trials"), backend="copy", prefer_git_worktree=False)
    )
    created = manager.create(source)

    loaded = manager.get(created.id)
    listed = manager.list()

    assert loaded is not None
    assert loaded.id == created.id
    assert [workspace.id for workspace in listed] == [created.id]


def test_discard_removes_workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("x = 1\n", encoding="utf-8")
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(tmp_path / "trials"), backend="copy", prefer_git_worktree=False)
    )
    workspace = manager.create(source)
    workspace_path = Path(workspace.workspace_path)

    assert manager.discard(workspace.id) is True

    assert not workspace_path.exists()
    assert manager.discard(workspace.id) is False


def test_unknown_backend_raises(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manager = TrialWorkspaceManager(TrialWorkspaceConfig(root=str(tmp_path / "trials")))

    with pytest.raises(ValueError):
        manager.create(source, backend="unknown")


def test_rejects_workspace_root_inside_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(source / ".termpilot-trials"), backend="copy")
    )

    with pytest.raises(ValueError, match="outside the source project"):
        manager.create(source)


def test_diff_and_apply_workspace_changes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("old\n", encoding="utf-8")
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(tmp_path / "trials"), backend="copy", prefer_git_worktree=False)
    )
    workspace = manager.create(source)
    workspace_path = Path(workspace.workspace_path)
    (workspace_path / "app.py").write_text("new\n", encoding="utf-8")
    (workspace_path / "extra.txt").write_text("added\n", encoding="utf-8")

    diff = manager.diff(workspace.id)

    assert diff.changed_files == 2
    assert "app.py" in diff.unified_diff
    assert "extra.txt" in diff.unified_diff

    applied = manager.apply(workspace.id)

    assert applied.changed_files == 2
    assert (source / "app.py").read_text(encoding="utf-8") == "new\n"
    assert (source / "extra.txt").read_text(encoding="utf-8") == "added\n"


def test_active_workspace_path_mapping(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(tmp_path / "trials"), backend="copy", prefer_git_worktree=False)
    )
    workspace = manager.create(source)

    set_active_trial_workspace(workspace)
    try:
        mapped = map_path_to_active_workspace(source / "hello.py")
    finally:
        set_active_trial_workspace(None)

    assert str(mapped).startswith(workspace.workspace_path)
    assert mapped.name == "hello.py"
    assert get_active_trial_workspace() is None


@pytest.mark.asyncio
async def test_file_tools_write_to_active_workspace(tmp_path):
    from termpilot.tools.read_file import ReadFileTool
    from termpilot.tools.write_file import WriteFileTool

    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "hello.py"
    source_file.write_text("print('source')\n", encoding="utf-8")
    manager = TrialWorkspaceManager(
        TrialWorkspaceConfig(root=str(tmp_path / "trials"), backend="copy", prefer_git_worktree=False)
    )
    workspace = manager.create(source)
    trial_file = Path(workspace.workspace_path) / "hello.py"

    set_active_trial_workspace(workspace)
    try:
        write_result = await WriteFileTool().call(
            file_path=str(source_file),
            content="print('trial')\n",
        )
        read_result = await ReadFileTool().call(file_path=str(source_file))
    finally:
        set_active_trial_workspace(None)

    assert "已写入" in write_result
    assert source_file.read_text(encoding="utf-8") == "print('source')\n"
    assert trial_file.read_text(encoding="utf-8") == "print('trial')\n"
    assert "print('trial')" in read_result
