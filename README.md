# TermPilot

[English](README.md) | [简体中文](README.zh-CN.md)

## Overview

`TermPilot` is a terminal-native AI coding assistant implemented in Python. It can read and edit files, execute commands, search code, call external tools, and manage long-running coding sessions from the command line.

It is already usable for day-to-day coding tasks and continues to evolve toward a more complete, production-ready terminal agent experience.

## Highlights

- Multi-provider API support: Anthropic, OpenAI, Zhipu GLM, DeepSeek, and Seed
- Streaming responses with Markdown-friendly terminal rendering
- Quiet terminal UI with staged status updates, compact tool cards, and on-demand detail expansion
- Tool-use loop: the model can call tools repeatedly until the task is complete
- Concurrent tool execution for safe tools, serialized execution for unsafe tools
- Permission system with five modes, persistent rules, path validation, and dangerous-command detection
- Optional sandbox runtime for bash commands with macOS `sandbox-exec` / Linux `bwrap` adapters and permission auto-allow when isolation is active
- Trial workspace mode for isolated edits, diff review, and explicit apply/discard before touching the source project
- Hook system for shell-command hooks around prompts and tool calls
- Automatic `TERMPILOT.md` loading for project-level persistent instructions
- Context compaction for long conversations
- Session persistence with resumable JSONL history, session rewind, and crash recovery
- Automatic retry with exponential backoff for API rate limits and transient failures
- MCP integration for dynamic tools and resources
- Skills and slash commands
- Delegation-oriented sub-agents: Explore, Plan, Verification, general-purpose, and user-defined custom agents (loaded from `~/.termpilot/agents/*.md`)
- Plan Mode: press Shift+Tab to cycle between Default, Accept Edits, and Plan modes; models in Plan mode are read-only and present plans for user approval
- Persistent memory, undo snapshots, token/cost tracking, large tool-result storage, and attachments

## Available Tools

| Tool | Name | Description | Concurrency-safe | Needs confirmation |
|------|------|-------------|------------------|--------------------|
| Directory summary | `list_dir` | Summarize a directory layout without dumping a full `ls`/`find` listing | ✅ | ❌ |
| Read file | `read_file` | Read file contents with line numbers, `offset`, and `limit` | ✅ | ❌ |
| Write file | `write_file` | Create or overwrite files and auto-create parent directories | ❌ | ✅ |
| Edit file | `edit_file` | Exact string replacement with optional `replace_all` | ❌ | ✅ |
| Run command | `bash` | Execute shell commands with timeout cleanup, cwd tracking, and optional sandbox wrapping | ❌ | ✅ |
| File search | `glob` | Search files using glob patterns | ✅ | ❌ |
| Content search | `grep` | Search file contents with regular expressions | ✅ | ❌ |
| Sub-agent | `agent` | Delegate work to Explore, Plan, Verification, general-purpose, custom agents, or a batch of up to 3 independent tasks | ✅ | ❌ |
| Agent runtime | `agent_send`, `agent_task_list`, `agent_task_get` | Continue existing AgentTask transcripts and inspect persistent sub-agent runtime records | Mixed | ❌ |
| Ask user | `ask_user_question` | Ask the user a focused follow-up question | ✅ | ❌ |
| Tasks | `task_create`, `task_update`, `task_list`, `task_get` | Track complex work as todo-style tasks with progress and dependencies | ✅ | ❌ |
| Plan mode | `enter_plan_mode`, `exit_plan_mode` | Switch into or out of planning mode | ✅ | ❌ |
| Notebook edit | `notebook_edit` | Edit Jupyter notebook cells | ❌ | ✅ |
| Web search | `web_search` | Search the web with optional domain filters | ✅ | ❌ |
| Web fetch | `web_fetch` | Fetch a URL with SSRF protection and convert HTML to Markdown | ✅ | ❌ |
| MCP tools | `mcp__*__*` | Dynamic tools exposed by MCP servers | ✅ | ❌ |
| MCP resources | `list_mcp_resources`, `read_mcp_resource` | List and read MCP resources | ✅ | ❌ |
| Skill tool | `skill` | Invoke reusable skill prompts | ✅ | ❌ |

## Quick Start

### Requirements

- Python 3.10+
- `pip`

### Install

```bash
pip install termpilot
```

To upgrade later:

```bash
pip install -U termpilot
```

### Configure

On first launch, TermPilot will guide you through an interactive setup:

```bash
termpilot
```

You'll see a provider selector:

```
? Select your LLM provider:
  > Anthropic (Claude)
    OpenAI
    Zhipu GLM
    DeepSeek
    Seed
```

Select your provider, enter your API key, and you're ready to go.

To reconfigure later:

```bash
termpilot model
```

Or manually edit `~/.termpilot/settings.json`:

```json
{
  "provider": "zhipu",
  "env": {
    "ZHIPU_API_KEY": "your-api-key",
    "ZHIPU_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "ZHIPU_MODEL": "glm-5.1"
  }
}
```

The setup wizard intentionally keeps the provider list short. Supported setup providers: Anthropic, OpenAI, Zhipu GLM, DeepSeek, and Seed. Existing OpenAI-compatible settings can still be configured manually with `TERMPILOT_BASE_URL`, `TERMPILOT_API_KEY`, and `TERMPILOT_MODEL`.

Environment variables override `settings.json`.

### Run

```bash
termpilot
termpilot -p "Read main.py"
termpilot -m gpt-4o
termpilot --resume
termpilot -s <session-id>
```

### Common Slash Commands

| Command | Description |
|---------|-------------|
| `/details last`, `/details <n>` | Show the full output for the most recent or a specific tool result |
| `/help` | Show available commands |
| `/compact` | Trigger manual context compaction |
| `/clear` | Clear conversation history |
| `/config` | Show effective configuration |
| `/model` | Switch the active model for the current provider |
| `/skills` | List available skills |
| `/mcp` | Show MCP server status |
| `/undo` | Restore the previous file snapshot |
| `/rewind` | Rewind conversation to a previous turn and continue from there |
| `/trial start`, `/trial diff`, `/trial apply`, `/trial discard`, `/trial clean` | Work in an isolated trial workspace, review changes, then apply, discard, or clean stale workspaces |
| `/commit` | Draft a commit flow with AI-generated commit message guidance |
| `/init` | Generate a project instruction seed for the current project |
| `/exit`, `/quit` | Exit the program |

## Sub-Agents

The `agent` tool delegates work to sub-agents that run in an isolated context with their own system prompt and tool set. Sub-agents can call tools until the task is complete, then return a final summary to the main agent.

TermPilot keeps the public tool name `agent`, but its intended semantics are closer to `delegate_task`: use `Plan` for implementation strategy, `Explore` for broad codebase understanding, `Verification` for checks and tests, and `general-purpose` for complex autonomous execution. For multiple independent directions, the model can pass a `tasks` array and delegate up to 3 sub-agents in one call. Batch delegation currently runs serially for predictable UI, permission, and result ordering.

Each spawned sub-agent is also registered as a persistent `AgentTask` with an `agent_id`, status, transcript path, and result path. When trial mode is active, the AgentTask metadata also records the active `workspace_id`, keeping delegated work linked to the isolated workspace where it ran. The `agent_send` tool can continue an existing local AgentTask transcript, while `agent_task_list` and `agent_task_get` expose the runtime records for inspection. Remote AgentTask execution is represented as a future extension point, but only the local adapter is implemented today.

| Type | Description |
|------|-------------|
| `Explore` | Fast read-only agent for codebase exploration, architecture analysis, file discovery, and code searches |
| `Plan` | Architect agent for designing implementation strategies and exploring trade-offs |
| `Verification` | Read-only agent for checking diffs, running tests, and identifying regressions |
| `general-purpose` | General agent for complex multi-step tasks with full tool access |
| Custom | User-defined agents loaded from `~/.termpilot/agents/*.md` with frontmatter metadata |

See [Task Delegation and Sub-Agent Routing](docs/task-delegation.md) for the design background and implementation details.

## Sandbox Runtime

TermPilot can optionally wrap `bash` commands with an operating-system sandbox. When `sandbox.enabled` is true and a backend is available, TermPilot can run shell commands through macOS `sandbox-exec` or Linux `bwrap`; if `autoAllowBashIfSandboxed` is enabled, sandboxed bash calls can skip the usual interactive confirmation.

The sandbox layer is a v1 runtime boundary, not a complete security product. It is designed as a small, UI-independent module so it can later move into a standalone runtime service. See [Sandbox Runtime](docs/sandbox-runtime.md) for configuration, flow, testing steps, and current limitations.

## Trial Workspace

TermPilot can run coding work in an isolated trial workspace before applying changes to the source project. Use `/trial start` to create a workspace, let the agent edit and run commands there, inspect changes with `/trial diff`, then either apply them with `/trial apply` or remove the workspace with `/trial discard`.

When `trialWorkspace.enabled` is true, TermPilot can conservatively auto-start a trial workspace for write-like prompts. `/trial apply` checks for source drift before copying changes back, and `/trial clean` removes stale non-active workspaces. The current implementation supports `git worktree` for Git repositories and a portable copy backend for manual testing or dirty working trees. See [Trial Workspace Runtime](docs/trial-workspace.md) for the flow, commands, settings, and limitations.

## Eval Harness

TermPilot includes a small TerminalBench-like eval harness under `evals/`. It runs `termpilot -p` against isolated task workspaces, executes deterministic verifier commands, and records `results.jsonl`, `summary.json`, `report.md`, logs, diffs, copied session JSONL, and portable `trajectories.jsonl` rows for regression analysis. See [Harness Engineering](docs/harness-engineering.md) for the roadmap and runner details.

### Custom Agents

Create a Markdown file in `~/.termpilot/agents/` with YAML frontmatter:

```markdown
---
name: code-reviewer
description: Reviews code for quality, security, and best practices
tools: read_file, glob, grep
---

You are a code review specialist. Analyze the code and report findings.
```

## Plan Mode

Press **Shift+Tab** to cycle between permission modes:

| Mode | Behavior |
|------|----------|
| Default | Normal operation with permission prompts |
| Accept Edits | Auto-approve file edits within the working directory |
| Plan | Read-only mode — only exploration and planning tools are allowed |

In Plan mode, the model explores the codebase and designs an implementation plan, then calls `exit_plan_mode` to present the plan for your approval via an interactive dialog. After approval, the mode restores to the previous setting.

A bottom toolbar shows the current mode (yellow for Plan, green for Accept Edits, gray for Default).

## Project Layout

```text
src/termpilot/
├── cli.py            # CLI entrypoint, quiet UI, permission menus, slash commands
├── api.py            # Tool loop, streaming, UI events, hooks, orchestration
├── context.py        # System prompt builder
├── config.py         # Settings and environment resolution
├── hooks.py          # Hook system
├── permissions.py    # Permission engine
├── messages.py       # Message normalization and helpers
├── session.py        # Session persistence
├── compact.py        # Context compaction
├── token_tracker.py  # Token counting and cost tracking
├── skills.py         # Skill loading and registry
├── commands.py       # Slash commands
├── termpilotmd.py    # TERMPILOT.md loading
├── sandbox/          # Sandbox config, backend adapters, and runtime decisions
├── workspace/        # Trial workspace runtime, diff, apply, and path mapping
├── mcp/              # MCP client, transport, and config
└── tools/            # Core tools, web tools, advanced tools, MCP adapters
```

## Architecture Summary

Main runtime flow:

1. `cli.py` collects user input and renders streamed output.
2. `context.py` builds the system prompt from environment, config, memory, and project instructions.
3. `api.py` calls the model, gathers `tool_use` blocks, and orchestrates tool execution.
4. `hooks.py` runs pre/post hooks and prompt/session hooks.
5. `permissions.py` decides whether each tool call is allowed, denied, or requires confirmation.
6. Tool results are returned to the model until it stops requesting tools.

For a deeper module breakdown, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Docs Map

- [ARCHITECTURE.md](ARCHITECTURE.md): layering, data flow, and module ownership
- [docs/golden-rules.md](docs/golden-rules.md): mechanical coding rules
- [docs/conventions.md](docs/conventions.md): naming and organization conventions
- [docs/hooks.md](docs/hooks.md): hook design and behavior
- [docs/compact.md](docs/compact.md): compaction strategy
- [docs/message-queue.md](docs/message-queue.md): interactive queue, drain loop, interrupts, and prompt handling
- [docs/sandbox-runtime.md](docs/sandbox-runtime.md): bash sandbox runtime, permission auto-allow, and backend decisions
- [docs/trial-workspace.md](docs/trial-workspace.md): isolated trial workspace, diff/apply flow, and commands
- [docs/mcp_skills.md](docs/mcp_skills.md): MCP, skills, and commands
- [docs/task-tool.md](docs/task-tool.md): task management, persistence, and dependency graph
- [docs/task-delegation.md](docs/task-delegation.md): task delegation and sub-agent routing
- [docs/system_prompt_sections.md](docs/system_prompt_sections.md): system prompt sections
- [docs/messages_attachments.md](docs/messages_attachments.md): message formats and file attachments
- [docs/test_cases/sandbox/sandbox_test_report.md](docs/test_cases/sandbox/sandbox_test_report.md): interactive sandbox behavior test report
- [docs/test_cases/subagent_tasks/agent_task_test_report_en.md](docs/test_cases/subagent_tasks/agent_task_test_report_en.md): sub-agent runtime, batch delegation, and follow-up test report

## Development Status

All planned phases are complete.

| Phase | Scope | Status |
|------|-------|--------|
| 1 | Tool framework and core tools | ✅ |
| 2 | System prompt sections | ✅ |
| 3 | Permission system | ✅ |
| 4 | Hooks system | ✅ |
| 5 | `TERMPILOT.md` loading | ✅ |
| 6 | Context compaction | ✅ |
| 7 | Messages and attachments | ✅ |
| 8 | Advanced tools: agent, task, ask-user, plan | ✅ |
| 9 | MCP, skills, and slash commands | ✅ |
| 10 | Remaining TypeScript alignment work | ✅ |
| 11 | P0 core capability completion: sub-agent recursion, chain backtracking, undo persistence, permission refinements | ✅ |

## Reference Implementation

The project is still being refined with reference to an upstream TypeScript implementation, but `TermPilot` keeps its own product identity, packaging, and documentation.

## UI Notes

- The default CLI experience is intentionally quiet: long raw tool output is collapsed into compact cards instead of being printed in full.
- When the model is still gathering context, the CLI shows short-lived staged statuses such as `Coalescing…`, project inspection, and summarization.
- Permission prompts use a keyboard-friendly menu (`↑` / `↓` + Enter) instead of numeric input.

## Development

If you want to work on TermPilot locally:

```bash
git clone https://github.com/frankzh0330/termpilot.git
cd termpilot

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
termpilot
```

For local quality checks:

```bash
python3 scripts/check.py
```

## License

MIT
