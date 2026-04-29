# Subagent Token Spend Aggregation

## Problem

The developer agent uses the `Task` tool to fan out work to implementer and reviewer subagents (per `superpowers:subagent-driven-development`). The token total reported in `state.json`, the TUI, and PR bodies looks too low — a 16-minute developer task shows only ↑1 ↓16k tokens, clearly missing subagent spend.

**Root cause** (`agentharness/agent_runner.py::_parse_json_output`, lines 188–224):

- `claude -p --output-format stream-json` emits NDJSON: one `system` init event, then many `assistant` / `user` / `tool_result` events, then a final `result` event.
- The parser tries `json.loads(entire_blob)` (fails — NDJSON), then falls back to the **last non-empty line** (the `result` event) and reads `usage.input_tokens` from it.
- Claude Code's final `result.usage` reflects the **parent session only**. Subagent (sidechain / Task-tool) usage arrives mid-stream as separate `assistant` events and is **not folded into** the parent's final `usage` block.
- `_format_stream_line` already sees those mid-stream events for human-readable logging but discards `message.usage`. Those tokens are silently dropped.

## Goal

Make the per-task `tokens_used` reflect parent + all subagents combined.

**Scope (minimal):**
- Fix the aggregate total only.
- No per-subagent breakdown stored in state.
- No `cost_usd` / dollar tracking added.
- No UI or `models.py` changes required.

## Solution

Replace the "parse only the last line" logic in `_parse_json_output` with a stream-walking aggregator:

1. Iterate every non-empty line, parse each as JSON (skip lines that fail).
2. For every event with `type == "assistant"`, read `message.usage` and add `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` to running totals.
3. This captures both parent assistant turns and sidechain (Task subagent) assistant turns — they share the same event shape.
4. Capture the final `type == "result"` event to extract the text output (`result` field).
5. Return `(text, TokenUsage(...))` — same contract as today, just correct.

`TokenUsage.__add__` already exists in `models.py`; use it for accumulation.

**Why this works:** All token usage in stream-json is exposed via `assistant.message.usage` blocks regardless of whether the turn is parent or sidechain. Summing across all of them = true total. No need to interpret `parent_tool_use_id` or track sidechain boundaries.

## Edge Cases

| Case | Behavior |
|------|----------|
| JSON parse failure on a line | Skip silently |
| `assistant` event missing `message.usage` | Zero contribution |
| No final `result` event (truncated stream) | Return aggregated tokens + best-effort text from assistant content |
| Non-stream-json / plain output | No JSON lines parse → return `(raw, None)` (existing contract) |
| Total of zero | Return `(text, None)` — callers skip storing empty `TokenUsage` |

## Files

### Modify

- `agentharness/agent_runner.py` — rewrite `_parse_json_output` to walk all stream-json lines

### Add

- `tests/test_agent_runner_parse.py` — unit tests for `_parse_json_output`:
  1. Single parent assistant turn + result → tokens = that one usage block
  2. Parent assistant + sidechain assistant → tokens = sum of both (regression test for this fix)
  3. Multiple sidechains (implementer + reviewer) → tokens = parent + all sidechains
  4. Malformed line mixed in → skipped, surrounding events still counted
  5. No final result event (truncated stream) → tokens still aggregated
  6. Empty / non-JSON output → returns `(raw, None)`

## Verification

```bash
# Unit tests
.venv/bin/pytest tests/test_agent_runner_parse.py -v
.venv/bin/pytest tests/ -v   # full suite, no regressions
```

Live check after deploy:
- Run a feature end-to-end with `agentharness observe`.
- When a developer task completes, check `state.json` → task `tokens_used`.
- Compare to the observer log: `_format_stream_line` logs every `assistant` event. Sum those manually; the stored total should match.
- Expect developer task token count to be **noticeably larger** (≥2× for implementer + reviewer fan-out).

## Out of Scope

- Per-subagent token breakdown in state / TUI / PR body.
- Dollar cost (`total_cost_usd`) tracking.
- `models.py` schema changes.
- Migration of old `state.json` files (old runs simply have lower legacy counts).