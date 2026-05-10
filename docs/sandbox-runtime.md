# Sandbox Runtime

[English](sandbox-runtime.md) | [简体中文](sandbox-runtime.zh-CN.md)

This document explains TermPilot's current sandbox and Bash runtime upgrade. The implementation is intentionally split into small, UI-independent modules so it can later be extracted into a standalone runtime or sandbox service.

## Why This Exists

TermPilot's `bash` tool is powerful: it can run tests, inspect repositories, execute scripts, and automate project workflows. That power needs guardrails. The sandbox runtime adds a first isolation layer around shell commands so TermPilot can reduce permission prompts when a command is actually constrained by an operating-system sandbox.

The current implementation is v1. It establishes the configuration model, backend abstraction, runtime decision path, BashTool integration, and permission-system integration. It is not yet a final production-grade security boundary.

## Runtime Flow

```text
Model requests bash
  │
  ▼
permissions.check_permission()
  │
  ├─ load sandbox config from ~/.termpilot/settings.json
  ├─ if a bash ask rule matches, first check whether sandbox auto-allow applies
  ├─ ask SandboxManager whether this command will really be sandboxed
  └─ auto-allow bash only when sandboxing is enabled and available
  │
  ▼
BashTool.call()
  │
  ├─ resolve persistent cwd
  ├─ load sandbox config again
  ├─ wrap command with SandboxManager if needed
  ├─ execute subprocess with process-group timeout cleanup
  ├─ update cwd after successful cd commands
  └─ fold large output before returning it to the model
```

If sandboxing is active, the BashTool output starts with:

```text
[sandboxed]
```

If the marker is missing, the command was executed without sandbox wrapping. Common causes are:

- `sandbox.enabled` is false or missing.
- No backend is available on the host.
- The command matches `excludedCommands`.
- Sandbox wrapping failed before execution.

## Settings

Add a top-level `sandbox` section to `~/.termpilot/settings.json`:

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

Important fields:

- `enabled`: turns sandbox decisions on.
- `autoAllowBashIfSandboxed`: lets `permissions.py` auto-allow bash only when `SandboxManager` confirms the command will be sandboxed.
- `dangerouslyDisableSandbox`: emergency kill switch.
- `excludedCommands`: command prefixes that must bypass sandboxing and use normal permission checks.
- `filesystem.allowWrite`: write scopes. `<cwd>` expands to the current project directory.
- `filesystem.denyWrite`: sensitive write-deny patterns.
- `network.denyDomains: ["*"]`: deny network by default for backends that support it.

## Module Responsibilities

```text
src/termpilot/sandbox/
├── __init__.py          public API
├── config.py            settings -> SandboxConfig dataclasses
├── base.py              SandboxAdapter interface
├── detect.py            platform backend detection
├── bubblewrap.py        Linux bwrap command wrapper
├── sandbox_exec.py      macOS sandbox-exec command wrapper
└── manager.py           SandboxDecision and orchestration boundary
```

### `config.py`

Reads `settings.json` and converts loose JSON into structured dataclasses:

- `SandboxConfig`
- `SandboxFilesystemConfig`
- `SandboxNetworkConfig`

It also expands `<cwd>` and injects protected write-deny patterns such as `.git`, `.ssh`, `.gnupg`, `.env`, and `.termpilot/settings.json`.

### `base.py`

Defines the adapter boundary:

```python
class SandboxAdapter:
    def is_available(self) -> bool: ...
    def wrap_command(self, command: str, config: SandboxConfig, cwd: str) -> str: ...
    def cleanup(self, cwd: str) -> None: ...
```

This is the main extraction seam for a future standalone sandbox runtime.

### `detect.py`

Chooses the platform backend:

- macOS: `SandboxExecAdapter`
- Linux: `BubblewrapAdapter`

The selected backend is discovered at runtime, not written to settings.

### `sandbox_exec.py`

Builds a macOS `sandbox-exec` profile and wraps the command:

```bash
sandbox-exec -p '<profile>' -- /bin/bash -lc '<command>'
```

The current profile uses a relaxed v1 shape:

- allow default behavior
- allow file reads
- allow writes under the project cwd and temp directories
- deny writes to sensitive paths
- optionally deny network access

This is practical for early runtime testing, but stricter profiles should be added later.

### `bubblewrap.py`

Builds a Linux `bwrap` command:

```bash
bwrap --ro-bind / / --bind <cwd> <cwd> --tmpfs /tmp --unshare-net -- /bin/bash -lc '<command>'
```

When network is denied globally, it adds `--unshare-net`.

### `manager.py`

Owns the runtime decision:

```python
SandboxManager.decide("echo hello", config)
```

returns:

```python
SandboxDecision(
    should_sandbox=True,
    reason="sandbox enabled",
    backend="sandbox-exec",
)
```

The decision only returns `should_sandbox=True` when:

- sandbox is enabled,
- `dangerouslyDisableSandbox` is false,
- the command does not match `excludedCommands`,
- and a backend is available.

## BashTool Runtime Changes

`src/termpilot/tools/bash.py` now handles more than simple subprocess execution:

- command classification with `classify_command()`,
- persistent cwd tracking across bash calls,
- sandbox wrapping before execution,
- process-group cleanup on timeout,
- large-output folding,
- `[sandboxed]` output marker when the sandbox wrapper is used.

Example:

```python
from termpilot.tools.bash import BashTool

tool = BashTool()
await tool.call(command="cd /tmp")
await tool.call(command="pwd")  # runs from /tmp
```

Timeout cleanup uses a new process session and kills the process group, not just the top-level shell process.

## Permission Integration

`permissions.py` still owns permission decisions. BashTool does not decide whether a command is allowed.

When checking a `bash` tool call, permissions now ask:

```text
Will this command actually run inside a sandbox?
```

If yes, and `autoAllowBashIfSandboxed` is true, the command is allowed without an interactive prompt. This also applies when a normal `ask` rule matches `bash`, matching Claude Code's behavior: the ask rule yields only when the command is guaranteed to be sandboxed. If no, the normal permission rules apply.

This avoids a dangerous mismatch where settings say sandbox is enabled but the host has no backend.

## Test Commands

Run focused tests:

```bash
uv run pytest tests/test_sandbox.py tests/tools/test_bash.py tests/test_permissions.py -q
```

Run the runtime-related regression set:

```bash
uv run pytest \
  tests/test_sandbox.py \
  tests/tools/test_bash.py \
  tests/test_permissions.py \
  tests/test_api.py \
  tests/test_compact.py \
  -q
```

Check runtime decision manually:

```bash
uv run python - <<'PY'
from termpilot.sandbox import get_sandbox_config, SandboxManager

config = get_sandbox_config()
print(config.enabled)
print(SandboxManager.decide("echo hello", config))
PY
```

Run a direct BashTool check:

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

When sandboxing is active, the output should include:

```text
[sandboxed]
hello
```

## Current Limitations

- This is a v1 runtime framework, not a complete security product.
- macOS uses `sandbox-exec`, which is deprecated and may need replacement later.
- Linux requires `bwrap` to be installed.
- Domain-level network allowlisting is not fully implemented.
- The macOS profile currently uses `allow default`; stricter `deny default` profiles should be introduced after compatibility testing.
- Agent worktree isolation is a separate future feature.

## Future Extraction Direction

The current seams are designed for extraction:

- `SandboxConfig` becomes a service API request object.
- `SandboxDecision` becomes a policy decision response.
- `SandboxAdapter` implementations can move behind a local daemon or worker process.
- BashTool can become a thin client that asks the runtime service to execute commands.
