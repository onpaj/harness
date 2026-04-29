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
