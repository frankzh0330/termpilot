# Trial Workspace Runtime

[English](trial-workspace.md) | [简体中文](trial-workspace.zh-CN.md)

This document explains TermPilot's Trial Workspace System: an isolated local workspace where the agent can edit files and run commands before the user applies the result back to the source project.

## Why This Exists

TermPilot is a local terminal coding agent. By default, local tools operate directly on the current project. That is fast and familiar, but it also means a mistaken file edit or command can affect the real working tree immediately.

Trial workspace mode introduces a safer path:

```text
source project
  │
  ├─ /trial start
  ▼
isolated trial workspace
  │
  ├─ agent edits / runs commands
  ├─ /trial diff
  ├─ /trial apply    → copy accepted changes back to source
  └─ /trial discard  → remove the trial workspace
```

This is similar to how remote coding agents, PR agents, and sandbox runtimes work, but implemented locally. The model still reasons about the source project path; TermPilot maps file/search/bash operations into the active trial workspace.

## User Flow

Start an isolated workspace:

```text
/trial start
```

Force the portable copy backend:

```text
/trial start --copy
```

Ask TermPilot to work as usual:

```text
Create hello_trial.py and run it.
```

Inspect changes:

```text
/trial diff
```

Apply changes to the source project:

```text
/trial apply
```

Discard the trial copy:

```text
/trial discard
```

Stop trial mode without deleting the workspace:

```text
/trial stop
```

## Slash Commands

| Command | Behavior |
|---------|----------|
| `/trial start` | Create and activate a trial workspace |
| `/trial start --copy` | Force the copy backend |
| `/trial status` | Show the active trial workspace |
| `/trial list` | List known trial workspaces |
| `/trial diff` | Show changed files and a unified diff |
| `/trial apply` | Apply trial changes back to the source project and deactivate trial mode |
| `/trial discard [id]` | Delete a trial workspace; defaults to the active workspace |
| `/trial stop` | Deactivate trial mode but keep the workspace |
| `/trial clean` | Remove stale non-active workspaces older than `ttlHours` |
| `/trial config` | Show effective trial workspace settings |

## Settings

Add a top-level `trialWorkspace` section to `~/.termpilot/settings.json`:

```json
{
  "trialWorkspace": {
    "enabled": false,
    "autoStart": true,
    "backend": "auto",
    "root": "~/.termpilot/trial-workspaces",
    "keepFailed": true,
    "ttlHours": 24,
    "preferGitWorktree": true,
    "copyExcludePatterns": [
      ".git",
      ".venv",
      "node_modules",
      "__pycache__",
      "dist",
      "build",
      "*.egg-info"
    ]
  }
}
```

Important fields:

- `backend`: `auto`, `git-worktree`, or `copy`.
- `autoStart`: when `enabled` is true, automatically create a trial workspace for prompts that look like they will modify files.
- `root`: where trial workspaces are created.
- `ttlHours`: age threshold used by `/trial clean`.
- `preferGitWorktree`: when `backend` is `auto`, prefer `git worktree` for Git repositories.
- `copyExcludePatterns`: directories and files skipped by the copy backend.

The current `/trial start` command works even if `enabled` is false. When
`enabled` is true, TermPilot can also auto-start a trial workspace for
write-like prompts such as "fix", "edit", "delete", "refactor", or "implement".
Set `autoStart` to false if you only want manual `/trial start` usage.

## Module Responsibilities

```text
src/termpilot/workspace/
├── __init__.py       public API
├── config.py         settings -> TrialWorkspaceConfig
├── backend.py        WorkspaceBackend protocol
├── copy_backend.py   portable shutil.copytree backend
├── git_backend.py    git worktree backend
├── manager.py        create/list/get/diff/apply/discard boundary
├── diff.py           changed-file summary and unified diff
├── apply.py          copy accepted changes back to source
└── runtime.py        active workspace context and path mapping
```

### `manager.py`

`TrialWorkspaceManager` is the service boundary. CLI commands should call the manager rather than constructing workspaces directly:

```python
manager.create(source_cwd, purpose="test")
manager.diff(workspace_id)
manager.apply(workspace_id)
manager.discard(workspace_id)
```

This keeps the design ready for a future standalone runtime service. The manager
also owns lifecycle operations such as marking a workspace `applied` or
`stopped`, cleaning stale workspaces, and refusing unsafe apply operations.

### `runtime.py`

The active workspace is process-local state. When trial mode is active, tools map source paths into the trial workspace:

```text
/project/hello.py
  -> ~/.termpilot/trial-workspaces/<id>/hello.py
```

Currently integrated tools:

- `read_file`
- `write_file`
- `edit_file`
- `list_dir`
- `glob`
- `grep`
- `bash`

## Backend Strategy

### Git worktree backend

Best for large Git repositories because it avoids copying the entire project. It uses:

```bash
git worktree add --detach <workspace> HEAD
```

Trade-off: it is based on `HEAD`, so uncommitted local changes are not automatically included.

### Copy backend

Best for manual testing, dirty working trees, and non-Git projects. It copies the current directory while skipping common large/generated paths.

Trade-off: it can be slower on large repositories.

## Interaction With Sandbox Runtime

Trial workspace and sandbox runtime solve different problems:

- Trial workspace isolates project changes and supports review/apply/discard.
- Sandbox runtime constrains shell command behavior.

They can be used together. When trial mode is active, BashTool runs with the trial workspace as cwd; if sandboxing is also active, sandbox write scope should point at that runtime cwd.

## Interaction With AgentTask Runtime

When a sub-agent is spawned while trial mode is active, its `AgentTask.metadata`
records the active `workspace_id`, `workspace_path`, and `source_cwd`. This keeps
sub-agent output linked to the isolated workspace where it was produced without
forcing full workspace details into every model message.

## Apply Safety

Trial workspace metadata stores source-file fingerprints at creation time. Before
`/trial apply` copies changes back, TermPilot checks whether any changed source
file drifted since the trial workspace was created.

If the source project changed, apply is refused and the conflicting files are
shown. This avoids overwriting user edits made in the real workspace while the
agent was working in the trial copy.

## Testing

Unit tests:

```bash
uv run pytest tests/test_workspace.py tests/test_commands.py tests/tools/test_bash.py tests/tools/test_write_file.py tests/tools/test_edit_file.py -q
```

Manual test:

```text
/trial start --copy manual-test
/trial status
Create hello_trial.py that prints "hello from trial" and run it.
/trial diff
/trial apply
/trial discard <workspace-id>
/trial clean
```

Expected behavior:

- Before `/trial apply`, the source project should not contain the new/edited file.
- `/trial diff` should show changed files and unified diff.
- `/trial apply` should refuse to apply if the source project changed after `/trial start`.
- After `/trial apply`, accepted non-conflicting changes appear in the source project.
- `/trial discard` removes the trial copy.
- `/trial clean` removes stale stopped/applied workspaces while preserving active ones by default.

## Current Limitations

- Automatic risk-based routing is intentionally conservative and only runs when `trialWorkspace.enabled=true`.
- Apply has source-drift detection, but patch backups and interactive conflict resolution are future work.
- Git worktree mode is based on `HEAD`, not dirty working tree state.
- The active workspace is process-local, not persisted across CLI restarts.
- Cleanup is command-driven through `/trial clean`; automatic background cleanup is not implemented yet.
