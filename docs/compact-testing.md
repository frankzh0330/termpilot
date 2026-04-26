# Compact Feature Testing Guide

This document provides step-by-step instructions for testing the context compaction system in TermPilot.

## Overview

The compact system has two levels:

- **Micro-compact**: Local text replacement, no LLM call. Two sub-strategies:
  - **Time-based**: Triggers when user idle > 60 min; clears old compactable tool results
  - **Count-based**: Triggers when compactable tool results > 10; truncates the oldest
- **Full-compact**: Uses LLM to generate a summary of older messages; keeps recent messages intact

Trigger chain: `estimate_tokens` → below threshold? → done | → micro-compact → still over? → full-compact

---

## Step 1: Run Existing Unit Tests

Verify the baseline is solid before interactive testing:

```bash
cd /Users/frank/frank_project/termpilot
python -m pytest tests/test_compact.py -v
```

Expected: 8 tests pass covering `estimate_tokens`, `micro_compact`, `_find_split_index`, `_extract_summary`, `_messages_to_text`, and `auto_compact_if_needed`.

---

## Step 2: Test `/compact` Command (Manual Trigger)

Start an interactive session and build up some conversation, then manually trigger compaction:

```bash
python -m termpilot
```

Build conversation context by asking the AI to read files:

```
Read the file src/termpilot/compact.py
Read the file src/termpilot/api.py
Read the file src/termpilot/context.py
Read the file src/termpilot/config.py
Read the file src/termpilot/hooks.py
```

Now trigger compaction manually:

```
/compact
```

**Expected output**: Something like:
```
Context compacted: 15,000 → 8,200 tokens (saved 6,800)
```

Verify:
- The session continues to work normally after compaction
- The AI can still reference recent messages in the conversation

---

## Step 3: Test Micro-Compact (Count-Based)

This strategy triggers when there are > 10 compactable tool results (from `read_file`, `bash`, `grep`, `glob`).

### 3.1 Generate enough tool calls to exceed the threshold

In a session, ask the AI to read many files one by one:

```
Read the following files and summarize each: compact.py, api.py, context.py, config.py, hooks.py, session.py, messages.py, permissions.py, undo.py, skills.py, commands.py, cli.py
```

This produces 12+ tool calls, exceeding the `MICROCOMPACT_MAX_TOOL_RESULTS = 10` threshold.

### 3.2 Verify truncation in logs

Enable debug logging to observe micro-compact behavior:

```bash
TERMPILOT_LOG_LEVEL=DEBUG python -m termpilot
```

After the 11th+ tool call, look for log output like:
```
Count-based micro-compact: truncated X/Y compactable tool results (whitelist: bash, glob, grep, read_file)
```

### 3.3 Verify the oldest results are truncated

After micro-compact triggers, ask:

```
What was in the first file you read?
```

**Expected**: The AI indicates it no longer has the full content of the earliest files (their tool results were truncated), but still remembers the most recent ones.

---

## Step 4: Test Micro-Compact (Time-Based)

This strategy triggers when the last assistant message is older than 60 minutes.

### 4.1 Simulate the idle gap

Since waiting 60 minutes is impractical, temporarily lower the threshold for testing. Edit `compact.py`:

```python
# Change from:
TIME_BASED_MC_GAP_MINUTES = 60

# To:
TIME_BASED_MC_GAP_MINUTES = 1  # for testing only
```

### 4.2 Test the time-based path

1. Start a session, make a few tool calls (read files, run grep, etc.)
2. Wait > 1 minute without sending any message
3. Send a new message (e.g., "hello")

**Expected in debug logs**:
```
Time-based micro-compact: gap=2min >= 1min, cleared X tool results (kept last 5), ~N tokens saved
```

### 4.3 Verify placeholder format

After time-based micro-compact, truncated tool results show:
```
[Old tool result content cleared] [tool=read_file]
```

Unlike count-based which shows:
```
[tool_result truncated: 12345 chars, tool=read_file]
```

### 4.4 Revert the threshold change

```python
TIME_BASED_MC_GAP_MINUTES = 60  # restore original
```

---

## Step 5: Test Full-Compact

Full-compact uses LLM to summarize older messages. It triggers when micro-compact is insufficient.

### 5.1 Force full-compact with `/compact`

In a session with enough conversation history:

```
/compact
```

If micro-compact alone reduces tokens below the threshold, the system won't call full-compact. To force it:

### 5.2 Lower the context window to force full-compact

Temporarily set a very small context window:

```bash
export TERMPILOT_CONTEXT_WINDOW=1000
```

Then start a session, have a conversation with several tool calls, and either:
- Let auto-compact trigger naturally, or
- Run `/compact`

### 5.3 Verify the compact summary format

After full-compact, the messages list contains a summary message like:

```
<compact-summary>
Earlier conversation has been summarized:

1. Primary Request and Intent: ...
2. Key Technical Concepts: ...
3. Files and Code Sections: ...
...
</compact-summary>
```

### 5.4 Verify conversation continuity

After full-compact, ask:

```
What files were involved before compaction?
```

**Expected**: The AI can answer from the summary, though with less detail than the original messages.

### 5.5 Revert the context window change

```bash
unset TERMPILOT_CONTEXT_WINDOW
```

---

## Step 6: Test Auto-Compact (Automatic Trigger)

Auto-compact is called in `api.py` before each API call. It triggers when estimated tokens exceed 75% of the context window.

### 6.1 Simulate a long conversation

The easiest way is to lower the context window temporarily:

```python
CONTEXT_WINDOW_DEFAULT = 5_000  # very small — triggers quickly
COMPACT_THRESHOLD_RATIO = 0.75  # 75% = 3,750 tokens triggers
```

### 6.2 Have a conversation that grows the context

```
Read the file src/termpilot/compact.py
Read the file src/termpilot/api.py
Read the file src/termpilot/context.py
Read the file src/termpilot/config.py
Now summarize what you know about the project
```

### 6.3 Observe auto-compact in logs

With debug logging enabled, logs show:

```
Context approaching limit: ~4500/5000 tokens (threshold: 3750)
Micro-compact reduced tokens: 4500 → 3200
```

Or if micro-compact isn't enough:

```
Running full-compact (micro: 4500 → 4200, force=False)
Full-compact: 4500 → 2500 tokens
```

### 6.4 Revert changes

```bash
unset TERMPILOT_CONTEXT_WINDOW
```

---

## Step 7: Test Compact with Non-Compactable Tools

Tools like `edit_file` and `write_file` are NOT in the compactable whitelist. Micro-compact never truncates their results.

### 7.1 Perform both compactable and non-compactable operations

```
Read the file src/termpilot/compact.py
Edit the file src/termpilot/compact.py — add a comment at the top
Read the file src/termpilot/api.py
```

### 7.2 Trigger micro-compact

After enough operations, check that:
- `read_file` results may be truncated (count-based or time-based)
- `edit_file` results are NEVER truncated — the old_string/new_string info must be preserved

---

## Step 8: Test Edge Cases

### 8.1 Empty conversation

```
/compact
```

**Expected**: `No messages to compact.`

### 8.2 Conversation with only text (no tool calls)

Have a text-only conversation (no file reads, no bash), then:

```
/compact
```

**Expected**: `Context not compacted: no meaningful reduction available.`

### 8.3 Full-compact failure (LLM error)

Temporarily break the client (e.g., set an invalid model name in settings), then trigger compact:

```
/compact
```

**Expected**: Graceful fallback — messages contain `[Context compression failed: ...]` instead of crashing.

---

## Quick Verification Table

| Step | Action | Expected Result |
|------|--------|----------------|
| 1 | `python -m pytest tests/test_compact.py -v` | 8 tests pass |
| 2 | `/compact` after reading files | Shows token reduction |
| 3 | 12+ tool calls → check logs | Count-based micro-compact log appears |
| 4 | Wait >60min → send message | Time-based micro-compact log appears |
| 5 | Force full-compact via small context window | `<compact-summary>` appears in messages |
| 6 | Long conversation with small window | Auto-compact triggers before API call |
| 7 | Mix of read_file + edit_file | Only read_file results are truncated |
| 8 | `/compact` with empty conversation | "No messages to compact." |

---

## Key Constants Reference

| Constant | Value | Purpose |
|----------|-------|---------|
| `TERMPILOT_CONTEXT_WINDOW` | 200,000 | Context window size override |
| `COMPACT_THRESHOLD_RATIO` | 0.75 | Trigger at 75% of context window |
| `COMPACT_TARGET_RATIO` | 0.50 | Compress to 50% after full-compact |
| `MICROCOMPACT_MAX_TOOL_RESULTS` | 10 | Count-based: keep last N results |
| `TIME_BASED_MC_GAP_MINUTES` | 60 | Time-based: idle threshold in minutes |
| `TIME_BASED_MC_KEEP_RECENT` | 5 | Time-based: keep last N results |
| `TOKEN_CHARS_RATIO` | 3 | ~3 chars = 1 token (estimation) |

## Compactable Tools Whitelist

Only these tools' results can be truncated by micro-compact:

- `read_file`
- `bash`
- `grep`
- `glob`

Tools NOT in the whitelist (e.g., `edit_file`, `write_file`) always have their results preserved.
