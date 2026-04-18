# Golden Rules

[English](golden-rules.md) | [简体中文](golden-rules.zh-CN.md)

These are the most important implementation rules reflected by the current codebase.

## 1. Tools implement the `Tool` protocol

Concrete tools in `tools/*.py` implement the `Tool` protocol from `tools/base.py`.

Why:

- keeps tools loosely coupled
- avoids deep inheritance
- makes registration in `tools/__init__.py` straightforward

## 2. Permission policy stays outside tools

Tool methods execute work; they do not decide whether that work is allowed.

Permission flow belongs to:

- `permissions.py`
- `api.py`
- `cli.py` for user confirmation UI

## 3. Hooks are a separate subsystem

Hook configuration loading and subprocess execution live in `hooks.py`. Call sites in `api.py` and `cli.py` should consume hook results instead of reimplementing hook behavior.

## 4. System prompt sections stay modular

`context.py` uses a mix of static section constants and small dynamic section builders. Keep section logic local and composable rather than building one large monolith.

## 5. Keep the tool loop centralized

The orchestration logic lives in `api.py`:

- stream model output
- collect tool calls
- run hooks
- check permissions
- execute tools
- append tool results
- repeat

Do not spread this flow across multiple layers.

## 6. Prefer deterministic local helpers first

If a problem can be solved with local transforms, cleanup, validation, or truncation, prefer that before adding model calls or new external dependencies.

Examples:

- token estimation before compaction
- local tool-result truncation/persistence
- path validation before file writes

## 7. Persist long-lived state explicitly

Use the existing subsystems instead of inventing ad hoc persistence:

- sessions → `session.py`
- undo snapshots → `undo.py`
- memory prompt/indexing → `context.py`
- large tool outputs → `tool_result_storage.py`

## 8. Match the staged rewrite philosophy

This project mirrors the TypeScript implementation at the subsystem level, but intentionally simplifies many parts. Prefer preserving behavior and clarity over copying complexity one-to-one.
