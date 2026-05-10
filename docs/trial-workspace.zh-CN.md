# Trial Workspace Runtime

[English](trial-workspace.md) | [简体中文](trial-workspace.zh-CN.md)

本文档说明 TermPilot 的 Trial Workspace System：让 agent 先在本地隔离工作区中编辑文件和运行命令，再由用户决定是否把结果应用回源项目。

## 为什么需要 Trial Workspace

TermPilot 是本地 terminal coding agent。默认情况下，本地工具会直接操作当前项目。这种方式快速、直观，但也意味着一次错误编辑或命令可能立刻影响真实工作区。

Trial workspace mode 提供了一条更安全的路径：

```text
源项目
  │
  ├─ /trial start
  ▼
隔离 trial workspace
  │
  ├─ agent 编辑 / 运行命令
  ├─ /trial diff
  ├─ /trial apply    → 把确认过的变更复制回源项目
  └─ /trial discard  → 删除 trial workspace
```

这类似远程 coding agent、PR agent 和 sandbox runtime 的工作方式，但实现发生在本地。模型仍然可以按源项目路径思考；TermPilot 会把文件、搜索和 bash 操作映射到 active trial workspace。

## 用户流程

创建隔离工作区：

```text
/trial start
```

强制使用 portable copy backend：

```text
/trial start --copy
```

像平时一样让 TermPilot 工作：

```text
创建 hello_trial.py 并运行它。
```

查看变更：

```text
/trial diff
```

应用变更到源项目：

```text
/trial apply
```

丢弃 trial 副本：

```text
/trial discard
```

退出 trial mode 但保留工作区：

```text
/trial stop
```

## Slash Commands

| 命令 | 行为 |
|------|------|
| `/trial start` | 创建并激活 trial workspace |
| `/trial start --copy` | 强制使用 copy backend |
| `/trial status` | 查看当前 active trial workspace |
| `/trial list` | 列出已知 trial workspaces |
| `/trial diff` | 查看变更文件和 unified diff |
| `/trial apply` | 将 trial 变更应用回源项目，并退出 trial mode |
| `/trial discard [id]` | 删除 trial workspace；默认删除 active workspace |
| `/trial stop` | 退出 trial mode，但保留 workspace |
| `/trial config` | 查看当前 trial workspace 配置 |

## 配置

在 `~/.termpilot/settings.json` 顶层加入 `trialWorkspace`：

```json
{
  "trialWorkspace": {
    "enabled": false,
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
      "build"
    ]
  }
}
```

关键字段：

- `backend`：`auto`、`git-worktree` 或 `copy`。
- `root`：trial workspaces 的创建位置。
- `preferGitWorktree`：当 `backend` 为 `auto` 时，Git 仓库优先使用 `git worktree`。
- `copyExcludePatterns`：copy backend 跳过的目录和文件。

当前 `/trial start` 即使在 `enabled` 为 false 时也可以使用。这个开关预留给后续自动进入 trial mode 的路由逻辑。

## 模块职责

```text
src/termpilot/workspace/
├── __init__.py       对外 API
├── config.py         settings -> TrialWorkspaceConfig
├── backend.py        WorkspaceBackend protocol
├── copy_backend.py   portable shutil.copytree backend
├── git_backend.py    git worktree backend
├── manager.py        create/list/get/diff/apply/discard 边界
├── diff.py           变更文件摘要和 unified diff
├── apply.py          将确认的变更复制回源项目
└── runtime.py        active workspace 上下文和路径映射
```

### `manager.py`

`TrialWorkspaceManager` 是 service boundary。CLI 命令应该调用 manager，而不是直接构造 workspace：

```python
manager.create(source_cwd, purpose="test")
manager.diff(workspace_id)
manager.apply(workspace_id)
manager.discard(workspace_id)
```

这样设计是为了后续可以抽离成独立 runtime service。

### `runtime.py`

active workspace 是进程内状态。trial mode 激活后，工具会把源项目路径映射到 trial workspace：

```text
/project/hello.py
  -> ~/.termpilot/trial-workspaces/<id>/hello.py
```

当前已接入的工具：

- `read_file`
- `write_file`
- `edit_file`
- `list_dir`
- `glob`
- `grep`
- `bash`

## Backend 策略

### Git worktree backend

适合大型 Git 仓库，因为它避免完整复制项目。它使用：

```bash
git worktree add --detach <workspace> HEAD
```

代价是：它基于 `HEAD` 创建，不会自动包含本地未提交改动。

### Copy backend

适合手动测试、脏工作区和非 Git 项目。它复制当前目录，并跳过常见大目录和生成目录。

代价是：大项目上会更慢。

## 与 Sandbox Runtime 的关系

Trial workspace 和 sandbox runtime 解决的问题不同：

- Trial workspace 隔离项目变更，并支持 review/apply/discard。
- Sandbox runtime 约束 shell 命令行为。

两者可以一起使用。trial mode 激活时，BashTool 会以 trial workspace 作为 cwd；如果 sandbox 也启用，sandbox 的写入范围应指向这个 runtime cwd。

## 测试

单元测试：

```bash
uv run pytest tests/test_workspace.py tests/test_commands.py tests/tools/test_bash.py tests/tools/test_write_file.py tests/tools/test_edit_file.py -q
```

手动测试：

```text
/trial start --copy manual-test
/trial status
创建 hello_trial.py，内容打印 "hello from trial"，并运行它。
/trial diff
/trial apply
/trial discard <workspace-id>
```

预期行为：

- 在 `/trial apply` 之前，源项目不应该出现新增/修改文件。
- `/trial diff` 应显示变更文件和 unified diff。
- `/trial apply` 后，确认过的变更会出现在源项目。
- `/trial discard` 会删除 trial 副本。

## 当前限制

- trial mode 目前是手动开启；还没有实现基于风险自动进入 trial mode。
- apply 当前会直接复制变更文件回源项目；source drift 检测和 patch 备份是后续工作。
- Git worktree mode 基于 `HEAD`，不是脏工作区状态。
- active workspace 是进程内状态，CLI 重启后不会自动恢复。
- cleanup/TTL 已规划但尚未实现。
