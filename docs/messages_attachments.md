# Messages, Attachments, and Large Tool Results

[English](messages_attachments.md) | [简体中文](messages_attachments.zh-CN.md)

This document describes the current message helper, attachment, and oversized-tool-result behavior.

## Relevant Modules

```text
messages.py             → message creation and normalization helpers
attachments.py          → local attachment processing
tool_result_storage.py  → persistence/truncation for large tool outputs
api.py                  → integrates stored/truncated tool results
cli.py                  → integrates attachment handling
```

## `messages.py`

The current helper module focuses on constructing consistent model-facing messages.

Key responsibilities:

- create user and assistant messages
- normalize message content into API-friendly shapes
- support tool-use / tool-result message forms used by the tool loop

## `attachments.py`

Attachments are processed before a user prompt is sent to the model.

Current responsibilities include:

- expanding referenced local files into message content
- formatting attachment content so it can be appended to the prompt safely

## `tool_result_storage.py`

Large tool outputs can quickly consume the context window. The current subsystem handles that by:

- deciding whether a tool result should be persisted
- writing oversized results to disk
- returning a preview-oriented replacement message for the live conversation
- truncating smaller-but-still-large outputs when persistence is unnecessary

## Why This Exists

Without this layer:

- `grep` output can dominate the transcript
- verbose shell output can crowd out reasoning context
- repeated tool calls can degrade model usefulness across long sessions

## Current Strategy

The current implementation uses a threshold-based approach:

- small output: keep inline
- medium output: truncate inline
- very large output: persist to disk and keep only a preview/reference in context

This works together with `compact.py`, which can later clear older tool results again if needed.
