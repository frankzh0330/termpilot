# Coding Conventions

[English](conventions.md) | [简体中文](conventions.zh-CN.md)

This document describes the main naming and file-organization conventions used in `termpilot`.

## Naming

| Item | Style | Example |
|------|-------|---------|
| Modules | `snake_case` | `read_file.py`, `tool_result_storage.py` |
| Classes | `PascalCase` | `PermissionMode`, `HookResult` |
| Functions | `snake_case` | `check_permission()`, `build_system_prompt()` |
| Constants | `UPPER_SNAKE_CASE` | `SAFE_TOOLS`, `MAX_CONCURRENT_TOOLS` |
| Private helpers | leading `_` | `_match_rule()`, `_build_hook_input()` |
| Dataclass fields | `snake_case` | `tool_name`, `exit_code` |

## File Organization

- one module per concept when possible
- top-level runtime modules live in `src/termpilot/`
- concrete tools live in `src/termpilot/tools/`
- MCP integration lives in `src/termpilot/mcp/`
- docs live in `docs/`
- small project scripts live in `scripts/`

## Typical Module Layout

Most modules roughly follow this structure:

1. module docstring with TypeScript counterpart notes
2. `from __future__ import annotations`
3. standard-library imports
4. third-party imports
5. project imports
6. constants
7. data structures / enums / dataclasses
8. public functions and helpers

## Import Order

Preferred order:

1. `from __future__ import annotations`
2. standard library
3. third-party packages
4. local project imports

## Design Conventions

- Keep tool implementations independent; they implement the `Tool` protocol rather than inheriting from a base class.
- Keep permission logic centralized in `permissions.py` / `api.py`, not inside tools.
- Keep hook execution centralized in `hooks.py`.
- Prefer explicit helper functions over deep inheritance trees.
- Match the current codebase style when editing existing modules.
