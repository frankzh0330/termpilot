# Building a Python Version of Claude Code: What I Learned by Rewriting It from Scratch

## Purpose

This project is **non-commercial, for personal learning only**. TermPilot is a personal project for studying Claude Code's excellent layered architecture, design patterns and technical discussion.

## References

All documentation is in the GitHub repository:

- **Source code:** [github.com/frankzh0330/termpilot](https://github.com/frankzh0330/termpilot)
- **Usage guide:** [README.md](https://github.com/frankzh0330/termpilot/blob/master/README.md) / [README.zh-CN.md](https://github.com/frankzh0330/termpilot/blob/master/README.zh-CN.md)
- **Architecture docs:** [ARCHITECTURE.md](https://github.com/frankzh0330/termpilot/blob/master/ARCHITECTURE.md) / [ARCHITECTURE.zh-CN.md](https://github.com/frankzh0330/termpilot/blob/master/ARCHITECTURE.zh-CN.md)
- **Module design docs:** [docs/](https://github.com/frankzh0330/termpilot/tree/master/docs) — hooks, compact, mcp, permissions, system prompt sections, etc.

## Why I Did This

Claude Code CLI is one of the best terminal AI coding assistants out there. Its layered architecture, tool-calling loop, permission system, and context management represent a high standard of engineering.

I would like to deeply understand these design — not only by reading source code, but by **rewriting it myself**. That's how TermPilot was born: a Python-from-scratch terminal AI coding assistant that replicates Claude Code's core architecture and features.

The project is live on PyPI and usable today:

```bash
pip install termpilot
termpilot
```

**Source code:** [github.com/frankzh0330/termpilot](https://github.com/frankzh0330/termpilot)

---

## What TermPilot Does

TermPilot is a terminal-native AI coding assistant that can read and edit files, execute commands, search codebases, call external tools, and manage long-running coding sessions — all from the command line.

### Key Features

| Capability | Description |
|---|---|
| Multi-provider support | Anthropic, OpenAI, Zhipu GLM, DeepSeek, Qwen, and 8+ more platforms |
| Streaming responses | Markdown-friendly terminal rendering |
| Tool-calling loop | Model calls tools repeatedly until the task is complete |
| Concurrent tool execution | Safe tools run in parallel; unsafe tools run sequentially |
| Permission system | 5 modes, persistent rules, path validation, dangerous command detection |
| Hook system | Shell command hooks around prompts and tool calls |
| Project instructions | Auto-loads `TERMPILOT.md` for project-level persistent guidance |
| Context compaction | Auto-compresses long conversations with a 3-tier strategy |
| Session persistence | Resumable JSONL history with generated titles |
| MCP integration | Dynamic tools and resources from MCP servers |
| Sub-agent system | Explore, Plan, and general-purpose agents |

### Supported Providers

First launch guides you through an interactive setup with 13+ LLM platforms:

```
? Select your LLM provider:
  > OpenAI
    Anthropic (Claude)
    Zhipu GLM
    DeepSeek
    Qwen / DashScope
    Moonshot / Kimi
    SiliconFlow
    OpenRouter
    Groq
    Together
    Fireworks
    Ollama (local)
    vLLM (local)
    OpenAI-compatible (custom)
```

---

## Architecture: What I Learned from Claude Code's Design

The overall architecture follows Claude Code's layering philosophy — modules are split into clear layers by responsibility.

```
┌─────────────────────────────────────────┐
│            CLI Layer (cli.py)            │
│   REPL loop · input rendering ·         │
│   permission UI · slash commands        │
├─────────────────────────────────────────┤
│         Orchestration (api.py)           │
│   Tool-calling loop · streaming ·       │
│   hook dispatch · permission gating     │
├─────────────────────────────────────────┤
│         Context Layer (context.py)       │
│   System prompt builder (13 sections)   │
├─────────────────────────────────────────┤
│          Tool Layer (tools/)             │
│   read/write/edit/bash/glob/grep/...    │
│   agent · task · plan · web · MCP       │
├─────────────────────────────────────────┤
│          Infrastructure                  │
│   permissions · hooks · session         │
│   compact · config · skills · MCP       │
└─────────────────────────────────────────┘
```

### The Core Runtime Flow

1. **`cli.py`** collects user input and renders streamed output
2. **`context.py`** builds the system prompt from environment, config, memory, and project instructions
3. **`api.py`** calls the model, gathers `tool_calls`, and orchestrates tool execution
4. **`hooks.py`** runs pre/post hooks around tool calls
5. **`permissions.py`** decides whether each tool call is allowed, denied, or needs confirmation
6. Tool results are returned to the model until it stops requesting tools

---

## 5 Design Decisions Worth Highlighting

### 1. The Unified Tool-Calling Loop

Claude Code's core is a single while loop: call LLM → if it returns `tool_use` → execute tools → send results back → repeat. TermPilot uses the same loop for all scenarios:

```python
for iteration in range(max_iterations):
    stream = call_llm(messages)
    for event in stream:
        if event is text: collect_text(event)
        if event is tool_use: collect_tool_call(event)

    if no_tool_calls: break  # Model is done

    results = execute_tools_concurrently(tool_calls)
    messages.extend(results)  # Next iteration
```

This elegant loop handles everything from simple Q&A to complex multi-step file editing.

### 2. Concurrent Tool Execution

Tools are classified as "concurrency-safe" (`read_file`, `glob`, `grep`) and "unsafe" (`write_file`, `edit_file`, `bash`). Within a single turn, safe tools execute in parallel while unsafe tools execute sequentially. This means 10 `glob`/`grep` calls can run simultaneously, dramatically reducing wait time.

### 3. Three-Tier Context Compaction

Long conversations cause token explosions. Claude Code's compaction strategy has three tiers:
1. Estimate tokens → below threshold → do nothing
2. Over threshold → micro-compact (clean old tool results, no LLM call)
3. Still over → full-compact (ask LLM to generate a summary)

TermPilot faithfully replicates this progressive approach.

### 4. Sub-Agent System with Specialized Roles

Three agent types, each with its own system prompt and tool set:
- **Explore**: Read-only search and analysis (uses `glob`, `grep`, `read_file`, `bash`)
- **Plan**: Architecture planning and design (read-only)
- **general-purpose**: Full tool access for autonomous multi-step work

Each sub-agent runs its own `query_with_tools` loop, enabling recursive tool calling.

### 5. Five-Layer Permission Check

Every tool call passes through five checks before execution:
1. Is it in the safe-tools whitelist? → Auto-allow
2. Does it match a persistent rule? (user previously chose "always allow") → Apply rule
3. Does it match a wildcard pattern? → Apply pattern
4. Is it intercepted by a hook? → Block or allow
5. None of the above → Prompt user for confirmation

---

## Project Structure

```text
src/termpilot/
├── cli.py            # CLI entrypoint, REPL, permission UI, slash commands
├── api.py            # Tool loop, streaming, hooks, orchestration
├── context.py        # System prompt builder (13 sections)
├── config.py         # Settings and environment resolution
├── hooks.py          # Hook system (5 lifecycle events)
├── permissions.py    # Permission engine (5 modes, 8-step check)
├── session.py        # Session persistence (JSONL)
├── compact.py        # Context compaction (micro + full)
├── token_tracker.py  # Token counting and cost tracking
├── skills.py         # Skill loading and registry
├── commands.py       # Slash commands
├── ui.py             # Terminal UI (compact tool cards, status spinner)
├── mcp/              # MCP client, transport, and config
└── tools/            # Core, web, advanced, MCP adapter tools
```

## Development Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Tool framework and core tools | ✅ Done |
| 2 | System prompt (13 sections) | ✅ Done |
| 3 | Permission system | ✅ Done |
| 4 | Hooks system | ✅ Done |
| 5 | `TERMPILOT.md` loading | ✅ Done |
| 6 | Context compaction | ✅ Done |
| 7 | Messages and attachments | ✅ Done |
| 8 | Advanced tools (agent, task, plan) | ✅ Done |
| 9 | MCP, skills, and slash commands | ✅ Done |
| 10 | UX polish (compact output, status indicators) | ✅ Done |
| 11 | Multi-provider native SDK support | ✅ Done |
| 12 | Parallel sub-agent orchestration | 🚧 Planned |

---

## What's Next

### 1. Auto-Recap After Turn Completion

After the model finishes a response (especially multi-iteration tool-call turns), show a brief recap summary and time spent — matching Claude Code's behavior:

```
✻ Churned for 1m 25s
※ Recap: Fixed /model command to show provider list with cursor on current provider.
```

**Design:**
- Track `_turn_start_time` and `_turn_message_idx` at the start of each REPL turn
- After response completes, calculate elapsed time
- Only generate LLM recap when the turn involved tool calls (multi-iteration)
- Use a lightweight prompt (`max_tokens=100`) to summarize the turn in one sentence
- Reuse `_messages_to_text()` from `compact.py` for text extraction
- Display with `✻` for time and `※` for recap, both in `[dim]` style

**Files:** `cli.py` (main change)

### 2. Parallel Sub-Agent Orchestration

Current sub-agents run serially. The plan is to add a "controller + parallel sub-agent execution" capability:

**Core idea:**
- New `ParallelAgentOrchestrator` — splits tasks, assigns write targets, launches parallel sub-agents
- Sub-agents work in a shared workspace, but write scopes are pre-allocated by the controller to prevent conflicts
- Terminal shows live progress: N tasks started → Agent X completed → N remaining → all done → summary

**V1 design constraints:**
- Shared workspace only (no worktree isolation)
- Sub-agents can write files, but write ranges must be pre-registered
- No auto-merge — conflict prevention only
- Final testing and commits remain the controller's responsibility
