"""Trajectory export tests."""

from __future__ import annotations

import json

from termpilot.trajectory import build_trajectory_from_session


def test_build_trajectory_from_session_jsonl(tmp_path):
    session_file = tmp_path / "session.jsonl"
    entries = [
        {
            "type": "transcript",
            "sessionId": "s1",
            "message": {"role": "user", "content": "Fix tests"},
        },
        {
            "type": "transcript",
            "sessionId": "s1",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "name": "bash",
                    "input": {"command": "pytest -q"},
                }],
            },
        },
        {
            "type": "transcript",
            "sessionId": "s1",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "content": "1 passed",
                }],
            },
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries),
        encoding="utf-8",
    )

    trajectory = build_trajectory_from_session(
        session_file,
        task_id="fix-tests",
        prompt="Fix tests",
        metadata={"model": "glm-5.1"},
        verifier={"passed": True, "exit_code": 0},
    )

    assert trajectory["task_id"] == "fix-tests"
    assert trajectory["conversations"][0] == {"from": "human", "value": "Fix tests"}
    assert trajectory["conversations"][1]["tool_calls"][0]["name"] == "bash"
    assert trajectory["conversations"][2] == {"from": "tool", "name": "", "value": "1 passed"}
    assert trajectory["metadata"]["session_id"] == "s1"
    assert trajectory["metadata"]["tool_count"] == 1
    assert trajectory["verifier"]["passed"] is True
