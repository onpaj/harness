# Specification: Subagent Token Spend Aggregation

## Summary
Fix the per-task `tokens_used` accounting in `agentharness/agent_runner.py` so it includes token spend from Task-tool subagents (implementer/reviewer fan-out), not just the parent Claude session. The current parser reads only the final `result` event from `claude -p --output-format stream-json`, which omits sidechain usage emitted as mid-stream `assistant` events. The fix replaces last-line parsing with a stream-walking aggregator that sums every `assistant.message.usage` block.

## Background
The developer agent uses Claude Code's `Task` tool (per `superpowers:subagent-driven-development`) to delegate implementation and review work to subagents. Each subagent consumes tokens that should be attributed to the parent developer task for accurate cost visibility.

Today, `_parse_json_output` (`agentharness/agent_runner.py:188-224`) handles the NDJSON stream like this:

1. Tries `json.loads(entire_blob)` — fails because output is line-delimited.
2. Falls back to parsing the **last non-empty line**, which is the `result` event.
3. Reads `usage.input_tokens` etc. from `result.usage`.

The problem: Claude Code's `result.usage` reflects **parent session only**. Sidechain (subagent) turns arrive earlier in the stream as their own `assistant` events with their own `message.usage` blocks, and those tokens are never folded into the final `result.usage`. `_format_stream_line` already sees these mid-stream events but discards their usage data.

Symptom: a 16-minute developer task that fans out to implementer + reviewer subagents reports only ↑1 ↓16k tokens in `state.json`, the TUI, and PR bodies — clearly missing the bulk of the spend.

## Functional Requirements

### FR-1: Aggregate token usage across all assistant events in the stream
`_parse_json_output` must iterate every non-empty line of `claude -p --output-format stream-json` output, parse each as JSON, and for every event with `type == "assistant"`, accumulate `message.usage` fields into a running `TokenUsage` total.

The fields summed are:
- `input_tokens`
- `output_tokens`
- `cache_creation_input_tokens`
- `cache_read_input_tokens`

This captures both parent assistant turns and sidechain (Task subagent) assistant turns, which share the same event shape. Use the existing `TokenUsage.__add__` operator from `models.py` for accumulation; do not introduce a new accumulation primitive.

**Acceptance criteria:**
- Given a stream with one parent assistant event and two sidechain assistant events, the returned `TokenUsage` equals the field-wise sum of all three `message.usage` blocks.
- Given only a parent assistant event (no sidechains), the returned `TokenUsage` matches that single block exactly.
- The function does **not** rely on the `result` event's `usage` field for token totals.

### FR-2: Extract final text output from the `result` event
The text returned by `_parse_json_output` must come from the final `type == "result"` event's `result` field (preserving today's behavior for callers that consume the agent's textual answer).

**Acceptance criteria:**
- When a `result` event is present, the returned text equals `event["result"]`.
- The text extraction is independent of the token aggregation pass — both happen in the same iteration.

### FR-3: Robust handling of malformed / partial streams
The aggregator must tolerate stream irregularities without raising:

| Case | Required behavior |
|------|-------------------|
| Line fails `json.loads` | Skip silently; continue to next line. |
| `assistant` event missing `message` or `message.usage` | Contribute zero; do not raise. |
| Stream truncated (no final `result` event) | Return aggregated tokens; text is best-effort: concatenate textual content from `assistant.message.content[*]` blocks where `type == "text"`, or empty string if none. |
| Non-stream-json / plain output (no parseable JSON lines) | Return `(raw_output, None)` — preserves existing contract. |
| Aggregated total is zero across all fields | Return `(text, None)` so callers skip storing an empty `TokenUsage`. |

**Acceptance criteria:**
- Each case in the table above has a dedicated unit test that asserts the documented behavior.
- No exception escapes `_parse_json_output` for any of the listed inputs.

### FR-4: Preserve return contract
`_parse_json_output` continues to return `tuple[str, TokenUsage | None]`. No changes to the function signature, no changes to call sites in `agent_runner.py` or downstream.

**Acceptance criteria:**
- `mypy` / type checks pass without changes to consumers.
- `agent_runner.py` integration points (the caller of `_parse_json_output`) are not modified.

### FR-5: Unit test coverage for the parser
Add `tests/test_agent_runner_parse.py` covering:

1. Single parent `assistant` turn + `result` → tokens = that one usage block.
2. Parent `assistant` + one sidechain `assistant` → tokens = sum of both (regression test for this fix).
3. Multiple sidechains (implementer + reviewer pattern) → tokens = parent + all sidechains, summed across all four token fields.
4. Malformed line interleaved with valid events → malformed line skipped, surrounding events still counted.
5. No final `result` event (truncated stream) → tokens still aggregated; text is best-effort or empty.
6. Empty / non-JSON output → returns `(raw, None)`.
7. Total of zero usage across all events → returns `(text, None)`.

**Acceptance criteria:**
- All seven scenarios are explicit, named tests.
- Tests run under `.venv/bin/pytest tests/test_agent_runner_parse.py -v` and pass.
- Full suite `.venv/bin/pytest tests/ -v` passes with no regressions.

## Non-Functional Requirements

### NFR-1: Performance
The aggregator iterates the stream once, O(n) in number of lines. For typical developer task streams (hundreds to low thousands of NDJSON lines), parsing overhead is negligible compared to the agent runtime itself. No streaming-while-running requirement — input is the already-collected stdout buffer, as today.

### NFR-2: Correctness over completeness
If a line cannot be parsed or an `assistant` event lacks `message.usage`, the aggregator silently skips that contribution rather than raising. Token undercounting is preferable to crashing the worker, since the dispatcher relies on `_parse_json_output` returning successfully to advance feature state.

### NFR-3: No new dependencies
Use only `json` from the standard library and the existing `TokenUsage` model. No new packages.

### NFR-4: Logging hygiene
Do not introduce per-line log spam. `_format_stream_line` already handles human-readable streaming output; the aggregator is purely a final-pass tally and should be silent on the happy path. Malformed lines may be logged at DEBUG but not WARN/ERROR.

## Data Model

No schema changes. `TokenUsage` already exists in `agentharness/models.py` with the four token fields and an `__add__` operator. `tokens_used` on `TaskEntry` continues to store a single `TokenUsage` representing the combined parent + subagent total for that task.

```
TokenUsage (existing, unchanged)
├── input_tokens: int
├── output_tokens: int
├── cache_creation_input_tokens: int
├── cache_read_input_tokens: int
└── __add__(other) → TokenUsage   # field-wise sum
```

## API / Interface Design

### Internal function contract (unchanged signature)

```python
def _parse_json_output(raw: str) -> tuple[str, TokenUsage | None]:
    """
    Parse claude -p --output-format stream-json output.

    Returns:
        (text, usage):
            text  — final result text, or best-effort assistant content if truncated.
            usage — aggregated TokenUsage across parent + all sidechain assistant
                    events, or None if no parseable JSON lines or zero total.
    """
```

### Stream event shapes consulted

```jsonc
// Aggregated for tokens
{ "type": "assistant", "message": { "usage": { "input_tokens": ..., "output_tokens": ..., "cache_creation_input_tokens": ..., "cache_read_input_tokens": ... }, "content": [{ "type": "text", "text": "..." }] } }

// Used for final text
{ "type": "result", "result": "..." }

// Ignored
{ "type": "system", ... }
{ "type": "user", ... }
{ "type": "tool_result", ... }
```

No CLI changes, no UI changes, no PR-body template changes — the existing rendering code consumes the corrected `TokenUsage` automatically.

## Dependencies

- `agentharness/models.py::TokenUsage` (existing) — provides the `__add__` operator.
- `claude -p --output-format stream-json` event schema — the fix relies on parent and sidechain `assistant` events sharing the same `message.usage` shape, which is documented behavior of Claude Code today.
- `pytest` / `pytest-asyncio` (existing dev dependencies) for the new test file.

## Out of Scope

- Per-subagent token breakdown stored in `state.json`, surfaced in the TUI, or rendered in the PR body.
- Dollar cost (`total_cost_usd`) tracking.
- Schema changes to `models.py` (`TokenUsage`, `TaskEntry`, or `FeatureState`).
- Backfill / migration of historical `state.json` files — older runs keep their (undercounted) legacy totals.
- Changes to `_format_stream_line` or the live observer log format.
- Changes to dispatcher, observer, run_task, or any caller of `_parse_json_output`.
- Handling of providers other than Claude Code stream-json.

## Open Questions

None.

## Status: COMPLETE