"""Portable trajectory export helpers.

The product session JSONL is optimized for resume/rewind. Eval and regression
analysis need a flatter, portable record that can be compared across runs or
used later for replay/training. This module is intentionally a conversion layer
instead of a replacement for session storage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_trajectory_from_session(
        session_path: str | Path | None,
        *,
        task_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
        verifier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one portable trajectory object from a TermPilot session JSONL file."""

    entries = _read_jsonl(Path(session_path)) if session_path else []
    conversations: list[dict[str, Any]] = []
    tool_count = 0
    session_id = ""

    for entry in entries:
        if entry.get("type") != "transcript":
            continue
        session_id = session_id or str(entry.get("sessionId") or "")
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        role = str(message.get("role") or "")
        content = message.get("content")
        converted, tools_in_turn = _convert_message(role, content)
        if converted:
            conversations.extend(converted)
            tool_count += tools_in_turn

    trajectory_metadata = {
        "session_id": session_id,
        "session_path": str(session_path) if session_path else "",
        "tool_count": tool_count,
        **(metadata or {}),
    }

    return {
        "task_id": task_id,
        "prompt": prompt,
        "conversations": conversations,
        "metadata": trajectory_metadata,
        "verifier": verifier or {},
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    entries.append(raw)
    except OSError:
        return []
    return entries


def _convert_message(role: str, content: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(content, str):
        return ([{"from": _role_name(role), "value": content}], 0) if role else ([], 0)

    if not isinstance(content, list):
        return [], 0

    converted: list[dict[str, Any]] = []
    tool_count = 0
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block_type == "tool_use":
            tool_count += 1
            converted.append({
                "from": "assistant",
                "value": "",
                "tool_calls": [{
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                }],
            })
        elif block_type == "tool_result":
            converted.append({
                "from": "tool",
                "name": block.get("name", ""),
                "value": str(block.get("content") or ""),
            })

    if text_parts:
        converted.insert(0, {"from": _role_name(role), "value": "\n".join(text_parts)})
    return converted, tool_count


def _role_name(role: str) -> str:
    if role == "user":
        return "human"
    if role == "assistant":
        return "assistant"
    return role or "unknown"
