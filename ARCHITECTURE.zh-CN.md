# 架构概览

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

本文档总结 `termpilot` 当前的整体架构、主要模块职责，以及层与层之间的依赖方向。

## 分层视图

```text
┌──────────────────────────────────────────────────────┐
│                    CLI Layer                         │
│                    cli.py                            │
│  REPL / 单次执行 · 安静型渲染                        │
│  权限菜单 · 工具卡片 · slash command 分发            │
│  会话启动                                            │
├──────────────────────────────────────────────────────┤
│                    API Layer                         │
│                    api.py                            │
│  模型客户端创建 · 流式响应 · 工具调用循环            │
│  hook 分发 · 权限检查 · 工具编排                     │
├──────────────────────────────────────────────────────┤
│                 Service Layer                        │
│  permissions.py · hooks.py · compact.py · undo.py   │
│  session.py · tool_result_storage.py · sandbox/*     │
│  workspace/*                                         │
├──────────────────────────────────────────────────────┤
│                 Context Layer                        │
│  context.py · config.py · messages.py                │
│  attachments.py · termpilotmd.py · skills.py        │
├──────────────────────────────────────────────────────┤
│                  Tool Layer                          │
│  核心工具 · 高级工具 · Web 工具                      │
│  MCP 适配器 · Skill 工具                             │
└──────────────────────────────────────────────────────┘
```

## 依赖方向

核心规则：依赖只向下流动。

```text
cli.py
  └─ api.py
      ├─ permissions.py / hooks.py / compact.py / undo.py
      ├─ context.py / config.py / messages.py / session.py
      ├─ attachments.py / tool_result_storage.py / termpilotmd.py / skills.py
      ├─ sandbox/*
      ├─ workspace/*
      └─ tools/*.py / mcp/*
```

约束原则：

- `cli.py` 负责交互和展示，不负责工具策略。
- `api.py` 负责模型与工具调用主循环。
- 服务模块尽量保持可复用，不反向依赖 CLI。
- 工具只关心执行，不关心权限策略。

## 模块职责

### `cli.py`

- 用 `click` 解析命令行参数
- 运行 REPL 和单次执行模式
- 初始化 session、undo、MCP、skills
- 分发 `SessionStart`、`UserPromptSubmit`、`Stop` hooks
- 用 `rich` 渲染 Markdown、阶段状态和紧凑工具卡片
- 保存最近的工具结果供 `/details` 查看
- 使用可键盘操作的权限确认菜单
- 处理 `commands.py` 中的 slash commands

### `api.py`

- 创建 Anthropic / OpenAI 兼容客户端
- 流式消费文本和 tool-use 事件
- 发出结构化 UI 事件（状态、权限、工具生命周期）
- 按安全/不安全工具分组执行
- 执行 `PreToolUse` / `PostToolUse` hooks
- 在工具执行前应用权限检查
- 对超大工具结果做持久化或截断后再回灌模型
- 在上下文过大时触发自动压缩

### `permissions.py`

- 定义 5 种权限模式：`DEFAULT`、`ACCEPT_EDITS`、`BYPASS`、`DONT_ASK`、`PLAN`
- 从 settings 中评估 allow / deny / ask 规则
- 校验敏感路径
- 检测危险 bash 命令
- bash 命中 ask rule 时，只有 sandbox 已启用、命令未被 excluded、且 backend 可用，才让 ask rule 让位并自动允许
- 生成供 `api.py` / `cli.py` 使用的 `PermissionResult`

### `sandbox/*`

- 将 sandbox settings 读取为 `SandboxConfig`
- 检测 macOS `sandbox-exec`、Linux `bwrap` 等平台 backend
- 在 bash 执行前生成 `SandboxDecision`
- sandbox 生效时，用选中的 backend 包装 shell 命令
- 保持与 UI 无关，方便后续抽离为独立 runtime service

### `workspace/*`

- 将 trial workspace settings 读取为 `TrialWorkspaceConfig`
- 通过 `git worktree` 或 portable copy backend 创建隔离工作区
- 记录 workspace metadata 和当前 active workspace 状态
- 生成可 review 的 diff，并在用户确认后应用回源项目
- 将源项目路径映射到 active trial workspace，供文件、搜索和 bash 工具使用
- 保持与 UI 无关，方便后续抽离为独立 workspace/runtime service

### `hooks.py`

- 从 `~/.termpilot/settings.json` 加载 hook 配置
- 定义 hook 事件与 matcher 结构
- 异步执行 shell command hook
- 解析 stdout JSON 中的 allow / deny / updated_input 信息

### `compact.py`

- 用本地启发式估算 token
- 执行 count-based 和 time-based micro-compact
- 必要时回退到模型生成摘要的 full compact

### `session.py`

- 将 transcript 以 JSONL 保存到 `~/.termpilot/projects/...`
- 通过 parent UUID 链恢复历史会话
- 存储会话标题等 metadata

### `context.py`

- 构建完整 system prompt
- 注入静态和动态 sections
- 加载 memory 指令和项目级指令
- 在 MCP server 提供 instructions 时注入到 prompt

### `messages.py`、`attachments.py`、`tool_result_storage.py`、`token_tracker.py`

- `messages.py`：消息构造与规范化
- `attachments.py`：本地附件展开
- `tool_result_storage.py`：超大工具输出持久化与截断
- `token_tracker.py`：从 API usage 提取精确 token 计数，按模型定价追踪费用

### `skills.py`、`commands.py`、`termpilotmd.py`

- `skills.py`：加载内置和磁盘上的 skills
- `commands.py`：内置 slash commands 与 skill fallback
- `termpilotmd.py`：按层级发现 `TERMPILOT.md` / rules 文件并注入 prompt

### `mcp/*` 与 `tools/*`

- `mcp/*`：传输层、客户端、配置与连接管理
- `tools/*`：暴露给模型的具体工具实现

当前工具族包括：

- 目录摘要工具：`list_dir`
- 核心文件/命令/搜索工具
- 高级工作流工具：ask-user、agent、task、plan、notebook
- 任务管理：`task_create`、`task_update`、`task_list`、`task_get`（详见 [docs/task-tool.zh-CN.md](docs/task-tool.zh-CN.md)）
- Trial workspace 命令：`/trial start`、`/trial status`、`/trial diff`、`/trial apply`、`/trial discard`
- Web 工具：`web_fetch`、`web_search`
- MCP 动态工具和资源读取工具
- Skill 展开工具

## 计划中的评测 Harness

计划把评测 harness 设计成一个 sidecar 工程层，而不是交互式 runtime path
的一部分。它会通过稳定的 CLI/API 入口驱动 TermPilot，隔离任务工作区，
记录 trajectory，运行确定性的 verifier，并生成用于回归追踪的报告。

这样可以让生产 agent loop 专注于用户交互，同时让项目具备可重复衡量任务完成质量的能力。
详细规划见 [docs/harness-engineering.zh-CN.md](docs/harness-engineering.zh-CN.md)。

## 运行时主流程

```text
用户输入
  │
  ▼
cli.py
  ├─ 处理附件 / slash commands
  ├─ 分发 UserPromptSubmit hook
  └─ 调用 api.query_with_tools()
        │
        ├─ 流式接收模型输出
        ├─ 收集 tool_use blocks
        ├─ 执行 PreToolUse hooks
        ├─ 权限检查
        ├─ 询问 sandbox runtime bash 是否可被隔离
        ├─ 如果启用了 active trial workspace，则映射工具路径
        ├─ 执行工具
        ├─ 执行 PostToolUse hooks
        ├─ 超大工具结果持久化或截断
        └─ 继续调用模型直到无 tool_use
  │
  ▼
cli.py 渲染最终输出
  │
  ▼
Stop hook
```

## 配置流

```text
~/.termpilot/settings.json
  ├─ config.py           → model / API key / base URL / env
  ├─ permissions.py      → 权限模式与规则
  ├─ sandbox/config.py   → bash sandbox runtime 策略
  ├─ workspace/config.py → trial workspace 策略
  ├─ hooks.py            → hook matchers
  └─ mcp/config.py       → MCP server 定义
```
