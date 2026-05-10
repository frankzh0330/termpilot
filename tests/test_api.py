"""API tool execution helpers."""

import pytest

from termpilot.api import (
    _apply_permission_rule_update,
    _call_openai_streaming,
    _compact_and_retry_messages,
    _is_context_overflow_error,
    _tool_result_success,
    query_with_tools,
)
from termpilot.permissions import PermissionBehavior, PermissionContext, PermissionRule


def test_agent_error_result_marks_tool_failed():
    assert _tool_result_success("agent", "Agent API error: timed out") is False
    assert _tool_result_success("agent", "Error: Agent prompt is required.") is False


def test_non_agent_string_result_is_successful():
    assert _tool_result_success("bash", "Error: command returned non-zero") is True


def test_permission_rule_update_replaces_opposite_in_memory_rule():
    ctx = PermissionContext(
        deny_rules=[
            PermissionRule(
                tool_name="bash",
                pattern="*",
                behavior=PermissionBehavior.DENY,
            )
        ]
    )

    _apply_permission_rule_update(ctx, {
        "tool_name": "bash",
        "pattern": "*",
        "behavior": "allow",
    })

    assert ctx.deny_rules == []
    assert len(ctx.allow_rules) == 1
    assert ctx.allow_rules[0].behavior == PermissionBehavior.ALLOW


def test_context_overflow_detection():
    assert _is_context_overflow_error(RuntimeError("context_length_exceeded")) is True
    assert _is_context_overflow_error(RuntimeError("413 Request Entity Too Large")) is True
    assert _is_context_overflow_error(RuntimeError("temporary network error")) is False


@pytest.mark.asyncio
async def test_compact_and_retry_uses_micro_compact_when_small(monkeypatch):
    messages = [{"role": "user", "content": "hello"}]
    compacted = [{"role": "user", "content": "short"}]

    monkeypatch.setattr("termpilot.api.micro_compact", lambda _: compacted)
    monkeypatch.setattr("termpilot.api.estimate_tokens", lambda _messages, _system: 10)

    async def fail_full_compact(*args, **kwargs):
        raise AssertionError("full_compact should not be called")

    monkeypatch.setattr("termpilot.api.full_compact", fail_full_compact)

    result = await _compact_and_retry_messages(
        messages,
        "system",
        object(),
        "model",
        context_window=100,
        client_format="openai",
    )

    assert result == compacted


@pytest.mark.asyncio
async def test_query_compacts_and_retries_stream_context_overflow(monkeypatch):
    calls = {"count": 0}

    async def fake_stream(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("context_length_exceeded")
        yield {"type": "text", "content": "ok"}

    async def fake_compact(messages, *args, **kwargs):
        return [{"role": "user", "content": "compacted"}]

    monkeypatch.setattr("termpilot.api._call_openai_streaming", fake_stream)
    monkeypatch.setattr("termpilot.api._compact_and_retry_messages", fake_compact)
    async def fake_auto_compact(messages, *args, **kwargs):
        return messages

    monkeypatch.setattr("termpilot.api.auto_compact_if_needed", fake_auto_compact)

    result = await query_with_tools(
        client=object(),
        model="model",
        system_prompt="system",
        messages=[{"role": "user", "content": "large"}],
        tools=[],
        client_format="openai",
    )

    assert result == "ok"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_openai_streaming_requests_and_yields_usage():
    class Usage:
        prompt_tokens = 123
        completion_tokens = 45

    class Chunk:
        choices = []
        usage = Usage()

    class Stream:
        async def __aiter__(self):
            yield Chunk()

    class Completions:
        def __init__(self):
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs
            return Stream()

    completions = Completions()
    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()

    events = [
        event async for event in _call_openai_streaming(
            client,
            "glm-5.1",
            "system",
            [{"role": "user", "content": "hi"}],
        )
    ]

    assert completions.kwargs["stream_options"] == {"include_usage": True}
    assert events == [{
        "type": "usage",
        "usage": {
            "input_tokens": 123,
            "output_tokens": 45,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }]
