# Sandbox Runtime

[English](sandbox-runtime.md) | [简体中文](sandbox-runtime.zh-CN.md)

本文档说明 TermPilot 当前的 sandbox 和 Bash runtime 改造。实现上刻意拆成小而独立、和 UI 无关的模块，方便后续抽象成独立 runtime 或 sandbox service。

## 为什么需要 Sandbox Runtime

TermPilot 的 `bash` 工具能力很强：可以跑测试、检查仓库、执行脚本、自动化项目流程。能力越强，越需要边界。sandbox runtime 的目标是在 shell 命令外加第一层隔离：当命令确实被操作系统 sandbox 限制住时，TermPilot 可以减少权限确认噪音。

当前实现是 v1。它建立了配置模型、backend 抽象、runtime 决策路径、BashTool 接入和权限系统联动，但还不是最终生产级安全边界。

## 运行流程

```text
模型请求 bash
  │
  ▼
permissions.check_permission()
  │
  ├─ 从 ~/.termpilot/settings.json 读取 sandbox 配置
  ├─ 如果 bash 命中 ask rule，先检查是否满足 sandbox 自动放行
  ├─ 询问 SandboxManager 这条命令是否真的会被 sandbox 包起来
  └─ 只有 sandbox 启用且可用时，才自动允许 bash
  │
  ▼
BashTool.call()
  │
  ├─ 解析持久 cwd
  ├─ 再次读取 sandbox 配置
  ├─ 需要时通过 SandboxManager 包装命令
  ├─ 用 subprocess 执行，并在超时时清理整个进程组
  ├─ 成功执行 cd 后更新 cwd
  └─ 折叠超大输出后返回给模型
```

如果 sandbox 生效，BashTool 输出会以：

```text
[sandboxed]
```

开头。

如果没有这个标记，说明命令没有经过 sandbox 包装。常见原因：

- `sandbox.enabled` 为 false 或缺失。
- 当前机器没有可用 backend。
- 命令命中了 `excludedCommands`。
- sandbox 包装在执行前失败。

## 配置

在 `~/.termpilot/settings.json` 顶层加入 `sandbox`：

```json
{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "dangerouslyDisableSandbox": false,
    "excludedCommands": ["git push"],
    "filesystem": {
      "allowWrite": ["<cwd>/**", "/tmp/termpilot-*"],
      "denyWrite": ["**/.git/**", "**/.env", "**/settings.json"],
      "allowRead": ["**"],
      "denyRead": ["**/.ssh/**", "**/.gnupg/**"]
    },
    "network": {
      "allowDomains": [],
      "denyDomains": ["*"],
      "allowLocalhost": false,
      "allowUnixSocket": false
    }
  }
}
```

关键字段：

- `enabled`：开启 sandbox 决策。
- `autoAllowBashIfSandboxed`：只有 `SandboxManager` 确认命令会被 sandbox 时，`permissions.py` 才自动允许 bash。
- `dangerouslyDisableSandbox`：紧急关闭开关。
- `excludedCommands`：绕过 sandbox、继续走普通权限检查的命令前缀。
- `filesystem.allowWrite`：允许写入范围。`<cwd>` 会展开为当前项目目录。
- `filesystem.denyWrite`：敏感写入拒绝规则。
- `network.denyDomains: ["*"]`：在 backend 支持时默认禁网。

## 模块职责

```text
src/termpilot/sandbox/
├── __init__.py          对外 API
├── config.py            settings -> SandboxConfig dataclasses
├── base.py              SandboxAdapter 接口
├── detect.py            平台 backend 检测
├── bubblewrap.py        Linux bwrap 命令包装
├── sandbox_exec.py      macOS sandbox-exec 命令包装
└── manager.py           SandboxDecision 和编排边界
```

### `config.py`

读取 `settings.json`，把松散 JSON 转成结构化 dataclass：

- `SandboxConfig`
- `SandboxFilesystemConfig`
- `SandboxNetworkConfig`

它还会展开 `<cwd>`，并注入受保护写入拒绝规则，例如 `.git`、`.ssh`、`.gnupg`、`.env`、`.termpilot/settings.json`。

### `base.py`

定义 adapter 边界：

```python
class SandboxAdapter:
    def is_available(self) -> bool: ...
    def wrap_command(self, command: str, config: SandboxConfig, cwd: str) -> str: ...
    def cleanup(self, cwd: str) -> None: ...
```

这是以后抽离成独立 sandbox runtime 的主要缝合点。

### `detect.py`

选择平台 backend：

- macOS：`SandboxExecAdapter`
- Linux：`BubblewrapAdapter`

backend 是运行时检测出来的，不写入 settings。

### `sandbox_exec.py`

生成 macOS `sandbox-exec` profile，并包装命令：

```bash
sandbox-exec -p '<profile>' -- /bin/bash -lc '<command>'
```

当前 profile 是偏宽松的 v1 形态：

- 默认允许系统行为
- 允许文件读取
- 允许写当前项目目录和临时目录
- 禁止写敏感路径
- 可选禁止网络访问

这适合早期 runtime 测试，但后续应该增加更严格的 profile。

### `bubblewrap.py`

生成 Linux `bwrap` 命令：

```bash
bwrap --ro-bind / / --bind <cwd> <cwd> --tmpfs /tmp --unshare-net -- /bin/bash -lc '<command>'
```

当网络被全局禁用时，会加入 `--unshare-net`。

### `manager.py`

负责 runtime 决策：

```python
SandboxManager.decide("echo hello", config)
```

返回：

```python
SandboxDecision(
    should_sandbox=True,
    reason="sandbox enabled",
    backend="sandbox-exec",
)
```

只有同时满足以下条件时，`should_sandbox` 才会是 true：

- sandbox 已启用；
- `dangerouslyDisableSandbox` 为 false；
- 命令没有命中 `excludedCommands`；
- 当前机器有可用 backend。

## BashTool Runtime 改造

`src/termpilot/tools/bash.py` 现在不只是简单 subprocess：

- 用 `classify_command()` 做命令分类；
- 在多次 bash 调用之间跟踪 cwd；
- 执行前按需包装 sandbox；
- 超时时清理整个进程组；
- 折叠超大输出；
- sandbox 生效时加 `[sandboxed]` 输出标记。

示例：

```python
from termpilot.tools.bash import BashTool

tool = BashTool()
await tool.call(command="cd /tmp")
await tool.call(command="pwd")  # 从 /tmp 执行
```

超时清理会创建新的 process session，并 kill 整个 process group，而不只是 kill 顶层 shell 进程。

## 权限系统联动

`permissions.py` 仍然负责权限决策。BashTool 不决定命令是否允许执行。

检查 `bash` 工具调用时，权限系统会先问：

```text
这条命令是否真的会在 sandbox 内运行？
```

如果答案是 yes，并且 `autoAllowBashIfSandboxed` 为 true，则无需交互确认直接允许。即使普通 `ask` 规则命中了 `bash`，也会先让位给这个 sandbox 自动放行判断，这和 Claude Code 的行为保持一致：只有确认命令真的会被 sandbox 包住时，ask rule 才会被跳过。如果答案是 no，则继续走原有权限规则。

这样可以避免“配置说开了 sandbox，但机器上其实没有 backend”的安全错觉。

## 测试命令

运行核心测试：

```bash
uv run pytest tests/test_sandbox.py tests/tools/test_bash.py tests/test_permissions.py -q
```

运行 runtime 相关回归测试：

```bash
uv run pytest \
  tests/test_sandbox.py \
  tests/tools/test_bash.py \
  tests/test_permissions.py \
  tests/test_api.py \
  tests/test_compact.py \
  -q
```

手动检查 runtime 决策：

```bash
uv run python - <<'PY'
from termpilot.sandbox import get_sandbox_config, SandboxManager

config = get_sandbox_config()
print(config.enabled)
print(SandboxManager.decide("echo hello", config))
PY
```

直接检查 BashTool：

```bash
uv run python - <<'PY'
import asyncio
from termpilot.tools.bash import BashTool

async def main():
    tool = BashTool()
    print(await tool.call(command="echo hello"))

asyncio.run(main())
PY
```

sandbox 生效时，输出应包含：

```text
[sandboxed]
hello
```

## 当前限制

- 这是 v1 runtime framework，不是完整安全产品。
- macOS 使用 `sandbox-exec`，该工具已 deprecated，后续可能需要替代方案。
- Linux 需要安装 `bwrap`。
- 域名级网络 allowlist 尚未完整实现。
- macOS profile 当前使用 `allow default`；兼容性测试稳定后，应增加更严格的 `deny default` profile。
- Agent worktree isolation 是后续独立功能。

## 后续抽离方向

当前边界已经为抽离做了准备：

- `SandboxConfig` 可以成为 service API request object。
- `SandboxDecision` 可以成为 policy decision response。
- `SandboxAdapter` 可以移到本地 daemon 或 worker process 后面。
- BashTool 可以变成一个薄 client，请 runtime service 执行命令。
