# Memory Feature Testing Guide

How the memory system works:

1. `context.py:load_memory_prompt()` reads `~/.termpilot/projects/<encoded-path>/memory/MEMORY.md` and injects it into the system prompt
2. The AI creates memory files (with frontmatter) via the Write tool and updates the `MEMORY.md` index
3. On the next conversation startup, `MEMORY.md` is loaded back into the system prompt, allowing the AI to "remember" previous information

---

## Prerequisites

Confirm the memory directory exists (auto-created after first run):

```bash
ls -la ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/
```

> An empty directory is expected for a fresh setup.

---

## Test Cases

### 1. Save a User-Type Memory

Start an interactive session:

```bash
cd /Users/frank/frank_project/termpilot
python -m termpilot
```

Input:

```
Please remember: I am a Python backend engineer, I prefer communicating in Chinese, and I like concise code style.
```

**Verify:**

```bash
cat ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/MEMORY.md
cat ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/user_profile.md
```

**Expected:** `MEMORY.md` contains an index line pointing to the memory file; the memory file contains frontmatter (name / description / type) + body content.

---

### 2. Cross-Session Memory Retrieval

Exit the current session (`/exit` or `Ctrl+C`), then restart:

```bash
python -m termpilot
```

Input:

```
Do you know my technical background and preferences?
```

**Expected:** The AI correctly answers from the memory loaded via MEMORY.md: Python backend engineer, prefers Chinese communication, likes concise code style.

---

### 3. Save a Feedback-Type Memory

In a session, input:

```
From now on, don't use emojis in your responses, and don't summarize what you did at the end
```

**Verify:**

```bash
ls ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/
cat ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/MEMORY.md
```

**Expected:** A new `feedback_*.md` file appears, and `MEMORY.md` index gains one more entry.

---

### 4. Save a Project-Type Memory

In a session, input:

```
The current project branch is feature/parallel-agents, planned for completion this month
```

**Verify:** Same as above — a new `project_*.md` file and corresponding index entry appears.

---

### 5. Multi-Type Memory Cross-Session Verification

Exit and start a new session:

```bash
python -m termpilot
```

Input:

```
What project am I currently working on? Do you remember my feedback preferences?
```

**Expected:** The AI correctly answers all information from memory (project branch + feedback preferences).

---

### 6. Memory Deletion (Forget)

In a session, input:

```
Forget my feedback preference about emojis
```

**Verify:**

```bash
cat ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/MEMORY.md
```

**Expected:** The corresponding feedback file is deleted, and the matching line in `MEMORY.md` is removed.

---

### 7. MEMORY.md Truncation Protection

Manually generate an index with over 200 lines to test truncation logic:

```bash
cd ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/

python3 -c "
lines = ['# MEMORY Index', '']
for i in range(210):
    lines.append(f'- [Memory {i}](memory_{i}.md) — test entry number {i} with some padding text')
with open('MEMORY.md', 'w') as f:
    f.write('\n'.join(lines))
"
```

Start a new session and check for truncation WARNING logs.

Clean up after testing:

```bash
rm ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/MEMORY.md
```

---

### 8. Run Unit Tests

```bash
cd /Users/frank/frank_project/termpilot
python -m pytest tests/test_context.py -v
```

Existing test coverage:
- `test_no_memory_dir` — Returns None when no memory directory exists
- `test_with_memory` — Content is injected when MEMORY.md exists
- Other context-related tests

---

## Quick Verification (3 Steps)

| Step | Action | Expected |
|------|--------|----------|
| Save memory | `python -m termpilot` → "Please remember I'm a Python engineer" | `.md` files appear in memory directory |
| Verify write | `cat ~/.termpilot/projects/.../memory/MEMORY.md` | Index entries present |
| Cross-session read | Exit → `python -m termpilot` → "Who am I?" | AI recalls correctly |

---

## Post-Test Cleanup

```bash
rm -rf ~/.termpilot/projects/-Users-frank-frank_project-termpilot/memory/*
```

---

## Memory File Format Reference

Each memory file uses the following frontmatter format:

```markdown
---
name: memory-name
description: one-line description (used to determine relevance)
type: user | feedback | project | reference
---

Body content

(Feedback / project types include **Why:** and **How to apply:** lines)
```

`MEMORY.md` is a pure index file, one entry per line:

```markdown
- [Title](filename.md) — one-line brief description
```
