"""Unit tests for _parse_json_output token aggregation across parent + sidechain assistant events."""

from __future__ import annotations

import json

from agentharness.agent_runner import _parse_json_output
from agentharness.models import TokenUsage


def _ndjson(*events: dict) -> str:
    """Serialize a sequence of events as newline-delimited JSON (Claude stream-json shape)."""
    return "\n".join(json.dumps(e) for e in events)


def _assistant_event(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    text: str = "",
) -> dict:
    """Build an `assistant` event with usage and optional text content."""
    content = [{"type": "text", "text": text}] if text else []
    return {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            "content": content,
        },
    }


def _result_event(text: str = "## Status: DONE") -> dict:
    return {"type": "result", "result": text}


def test_single_parent_assistant_and_result():
    """Single parent assistant event + result → tokens equal that one usage block, text from result."""
    raw = _ndjson(
        _assistant_event(input_tokens=100, output_tokens=50, cache_read=10, text="hi"),
        _result_event("done"),
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "done"
    assert tokens == TokenUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=10,
    )


def test_parent_plus_one_sidechain():
    """Parent assistant + one sidechain assistant + result → tokens are summed.

    Regression test for the bug where only the parent (final result.usage) was counted.
    The sidechain assistant turn appears mid-stream, before the result event.
    """
    raw = _ndjson(
        _assistant_event(input_tokens=12_000, output_tokens=800, cache_read=4096),  # sidechain
        _assistant_event(input_tokens=1, output_tokens=16_000),                     # parent
        _result_event("## Status: DONE"),
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "## Status: DONE"
    assert tokens == TokenUsage(
        input_tokens=12_001,
        output_tokens=16_800,
        cache_creation_tokens=0,
        cache_read_tokens=4_096,
    )


def test_multiple_sidechains():
    """Parent + implementer subagent + reviewer subagent + result.

    Verifies field-name translation: the wire's `cache_creation_input_tokens` and
    `cache_read_input_tokens` must populate `TokenUsage.cache_creation_tokens` and
    `cache_read_tokens` respectively (not the same name).
    """
    raw = _ndjson(
        # implementer subagent
        _assistant_event(input_tokens=10_000, output_tokens=2_000, cache_creation=500, cache_read=1_000),
        # reviewer subagent
        _assistant_event(input_tokens=8_000, output_tokens=1_500, cache_creation=300, cache_read=2_000),
        # parent assistant final turn
        _assistant_event(input_tokens=2, output_tokens=500, cache_creation=0, cache_read=4_000),
        _result_event("## Status: DONE"),
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "## Status: DONE"
    assert tokens == TokenUsage(
        input_tokens=18_002,
        output_tokens=4_000,
        cache_creation_tokens=800,
        cache_read_tokens=7_000,
    )


def test_malformed_line_interleaved():
    """A line that is not valid JSON between valid events is skipped silently;
    surrounding events are still parsed and counted."""
    valid_assistant = json.dumps(_assistant_event(input_tokens=100, output_tokens=50))
    valid_result = json.dumps(_result_event("ok"))
    raw = "\n".join([
        valid_assistant,
        "not json at all { ::: }",   # malformed line
        valid_assistant,             # second identical assistant turn
        valid_result,
    ])

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "ok"
    assert tokens == TokenUsage(input_tokens=200, output_tokens=100)


def test_truncated_stream_no_result():
    """Stream with no `result` event → tokens still aggregate; text falls back
    to the LAST assistant event's last text block (not concatenated)."""
    raw = _ndjson(
        _assistant_event(input_tokens=100, output_tokens=50, text="early thought"),
        _assistant_event(input_tokens=200, output_tokens=80, text="final partial answer"),
        # no result event — stream truncated
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "final partial answer"
    assert tokens == TokenUsage(input_tokens=300, output_tokens=130)


def test_empty_non_json_output():
    """Plain text output (no parseable JSON lines) → returns (raw, None)."""
    raw = "this is plain text, claude never produced stream-json\nsecond line"

    text, tokens = _parse_json_output(raw, "developer")

    assert text == raw
    assert tokens is None


def test_empty_string_input():
    """Empty input → returns ("", None) without raising."""
    text, tokens = _parse_json_output("", "developer")

    assert text == ""
    assert tokens is None


def test_zero_usage_total():
    """All assistant events present but every usage field is zero → (text, None)."""
    raw = _ndjson(
        _assistant_event(input_tokens=0, output_tokens=0, text="thinking"),
        _result_event("done"),
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "done"
    assert tokens is None


def test_assistant_event_missing_usage_block():
    """Assistant event without `message.usage` contributes zero, does not raise."""
    event_without_usage = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hi"}]},
    }
    raw = _ndjson(
        event_without_usage,
        _assistant_event(input_tokens=10, output_tokens=5),
        _result_event("done"),
    )

    text, tokens = _parse_json_output(raw, "developer")

    assert text == "done"
    assert tokens == TokenUsage(input_tokens=10, output_tokens=5)
