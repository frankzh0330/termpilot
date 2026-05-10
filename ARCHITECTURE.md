# Architecture Overview

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

This document summarizes the current architecture of `termpilot`, the responsibility of each major module, and the intended dependency direction between layers.

## Layered View

```text
┌──────────────────────────────────────────────────────┐
│                    CLI Layer                         │
│                    cli.py                            │
│  REPL / one-shot mode · quiet rendering              │
│  permission menu · tool cards · slash command        │
│  dispatch · session startup                          │
├──────────────────────────────────────────────────────┤
│                    API Layer                         │
│                    api.py                            │
│  model client creation · streaming · tool loop       │
│  hook dispatch · permission gating · orchestration   │
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
│  core tools · advanced tools · web tools             │
│  MCP adapters · skill tool                           │
└──────────────────────────────────────────────────────┘
```

## Dependency Direction

Core rule: dependencies flow downward.

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

Guidelines:

- `cli.py` owns UI and user interaction, not tool policy.
- `api.py` owns the model/tool execution loop.
- Service modules should stay reusable and not depend on the CLI layer.
- Tools should focus on execution, not permission policy.

## Module Responsibilities

### `cli.py`

- Parses CLI arguments with `click`
- Runs REPL and one-shot execution
- Initializes sessions, undo state, MCP, and skills
- Dispatches `SessionStart`, `UserPromptSubmit`, and `Stop` hooks
- Renders markdown, staged statuses, and compact tool cards with `rich`
- Stores recent tool results for `/details`
- Uses keyboard-friendly permission menus
- Handles slash commands from `commands.py`

### `api.py`

- Creates Anthropic/OpenAI-compatible clients
- Streams text and tool-use events
- Emits structured UI events for status, permission, and tool lifecycle changes
- Executes tool calls with safe/unsafe concurrency partitioning
- Runs `PreToolUse` and `PostToolUse` hooks
- Applies permission checks before tool execution
- Stores or truncates large tool results before re-injecting them
- Triggers auto compaction when context grows too large

### `permissions.py`

- Defines five permission modes: `DEFAULT`, `ACCEPT_EDITS`, `BYPASS`, `DONT_ASK`, `PLAN`
- Evaluates allow/deny/ask rules from settings
- Validates sensitive file paths
- Classifies dangerous bash commands
- Lets bash ask rules yield only when sandboxing is enabled, the command is not excluded, and a backend is available
- Produces `PermissionResult` objects consumed by `api.py` and `cli.py`

### `sandbox/*`

- Loads sandbox settings into `SandboxConfig`
- Detects platform backends such as macOS `sandbox-exec` and Linux `bwrap`
- Produces `SandboxDecision` objects before bash execution
- Wraps shell commands with the selected backend when sandboxing is active
- Stays UI-independent so it can later be extracted into a standalone runtime service

### `workspace/*`

- Loads trial workspace settings into `TrialWorkspaceConfig`
- Creates isolated workspaces with `git worktree` or a portable copy backend
- Tracks workspace metadata and active workspace state
- Builds reviewable diffs and applies accepted changes back to the source project
- Maps source-project paths into the active trial workspace for file, search, and bash tools
- Stays UI-independent so it can later be extracted into a standalone workspace/runtime service

### `hooks.py`

- Loads hook configuration from `~/.termpilot/settings.json`
- Defines hook events and matcher structures
- Executes shell-command hooks asynchronously
- Parses hook stdout JSON for allow/deny/input-update behavior

### `compact.py`

- Estimates token usage with a local heuristic
- Performs count-based and time-based micro-compaction
- Falls back to model-generated full compaction when needed

### `session.py`

- Persists transcript entries as JSONL under `~/.termpilot/projects/...`
- Restores session history by replaying the parent UUID chain
- Stores metadata such as generated conversation titles

### `context.py`

- Builds the full system prompt
- Injects static prompt sections and dynamic sections
- Loads memory guidance and project instructions
- Includes MCP instructions when connected servers provide them

### `messages.py`, `attachments.py`, `tool_result_storage.py`, `token_tracker.py`

- `messages.py`: message construction and normalization helpers
- `attachments.py`: local attachment expansion for prompts
- `tool_result_storage.py`: persistence/truncation of oversized tool outputs
- `token_tracker.py`: exact token counting from API usage and per-model cost tracking

### `skills.py`, `commands.py`, `termpilotmd.py`

- `skills.py`: loads bundled and disk-based skills
- `commands.py`: builtin slash commands plus skill fallback
- `termpilotmd.py`: discovers layered `TERMPILOT.md` / rules files for prompt injection

### `mcp/*` and `tools/*`

- `mcp/*`: transport, client, config, and connection management
- `tools/*`: concrete tools exposed to the model

Current tool families:

- Directory summary tool: `list_dir`
- Core file/shell/search tools
- Advanced workflow tools: ask-user, agent, task, plan, notebook
- Task management: `task_create`, `task_update`, `task_list`, `task_get` (see [docs/task-tool.md](docs/task-tool.md))
- Trial workspace commands: `/trial start`, `/trial status`, `/trial diff`, `/trial apply`, `/trial discard`
- Web tools: `web_fetch`, `web_search`
- MCP dynamic tools and resource readers
- Skill expansion tool

## Planned Evaluation Harness

The evaluation harness is planned as a sidecar engineering layer, not part of
the interactive runtime path. It will drive TermPilot through stable CLI/API
entry points, isolate task workspaces, record trajectories, run deterministic
verifiers, and produce reports for regression tracking.

This keeps the production agent loop focused on user interaction while giving
the project a repeatable way to measure task completion quality. The detailed
plan is documented in [docs/harness-engineering.md](docs/harness-engineering.md).

## Runtime Flow

```text
User input
  │
  ▼
cli.py
  ├─ process attachments / slash commands
  ├─ dispatch UserPromptSubmit hook
  └─ call api.query_with_tools()
        │
        ├─ stream model output
        ├─ collect tool_use blocks
        ├─ run PreToolUse hooks
        ├─ check permissions
        ├─ ask sandbox runtime whether bash can be isolated
        ├─ map tool paths into active trial workspace if enabled
        ├─ execute tools
        ├─ run PostToolUse hooks
        ├─ store/truncate tool results if needed
        └─ call model again until no tool_use remains
  │
  ▼
cli.py renders final response
  │
  ▼
Stop hook
```

## Configuration Flow

```text
~/.termpilot/settings.json
  ├─ config.py           → model / API key / base URL / env
  ├─ permissions.py      → permission rules and mode
  ├─ sandbox/config.py   → bash sandbox runtime policy
  ├─ workspace/config.py → trial workspace policy
  ├─ hooks.py            → hook matchers
  └─ mcp/config.py       → MCP server definitions
```
