# Architecture Review: Subagent Token Spend Aggregation

## Architectural Fit Assessment

This is a **localized parser bugfix**, not an architectural change. The fix lives entirely inside `_parse_json_output` in `agentharness/agent_runner.py:188`. The function's role — translating Claude CLI stdout into `(text, TokenUsage)` for downstream attribution — is unchanged; only its scan strategy is wrong (last-line-only) and must become whole-stream.

Integration points stay the same:

- **Caller** (`run_agent`, line 106): consumes `(text, tokens)` and logs/returns; unaware of how tokens were derived.
- **Downstream** (`run_task.py`, dispatcher, TUI, PR rendering): read the resulting `TokenUsage` from `TaskEntry.tokens_used` / `PhaseInfo.tokens_used`. No schema, no transport changes.
- **Model** (`models.py:42-58`): `TokenUsage.__add__` already provides field-wise accumulation — the only primitive needed.

The fix is well-aligned with existing patterns: stream-walking via `json.loads` per line is already done by `_format_stream_line` (line 117) for human-readable output. We are reusing that iteration shape for a tally pass.

## Proposed Architecture

### Component Overview

```
            stdout (NDJSON)
                  │
                  ▼
   ┌──────────────────────────────┐
   │   _stream_stdout (existing)  │  per-line: append + format-log
   └──────────────────────────────┘
                  │
                  ▼ raw_output: "\n".join(lines)
   ┌──────────────────────────────┐
   │   _parse_json_output (REWRITE)│
   │                              │
   │   for line in raw.splitlines:│
   │     event = try json.loads   │  → skip on JSONDecodeError
   │     if type=="assistant":    │  → tokens += from message.usage
   │     if type=="result":       │  → text   = event["result"]
   │     else (truncation):       │  → text  ⟵ best-effort assistant text
   │                              │
   │   return (text, tokens or None)│
   └──────────────────────────────┘
                  │
                  ▼  (text, TokenUsage|None)
              run_agent → RunResult → caller
```

A single sweep, two accumulators (`tokens: TokenUsage`, `text: str`), zero new types.

### Key Design Decisions

#### Decision 1: Single-pass aggregator vs. two-pass / stateful parser
**Options considered:**
- A. Two passes — first to find the `result` event, second to sum tokens.
- B. Single pass — accumulate tokens and capture result text in one iteration.
- C. State-machine class wrapping the parse.

**Chosen approach:** B — one iteration over `raw.splitlines()` with two locals (`tokens`, `result_text`).

**Rationale:** O(n) and cache-friendly, simpler than two passes, avoids over-engineering with a class. Matches the per-line shape `_format_stream_line` already uses.

#### Decision 2: Source-of-truth for tokens — `assistant.message.usage` only
**Options considered:**
- A. Mix `result.total_*_tokens` (parent) with mid-stream `assistant.message.usage` for sidechains, deduplicated by `parent_tool_use_id`.
- B. Sum **only** `assistant.message.usage` blocks, regardless of parent vs. sidechain.

**Chosen approach:** B.

**Rationale:** Claude Code emits `usage` on every `assistant` event, parent and sidechain alike — same shape, no overlap. Mixing sources risks double counting if Claude's behavior changes. `result.usage` is no longer load-bearing for the total; we only consult `result.result` for text. This matches the spec's FR-1 explicitly.

#### Decision 3: Truncated-stream behavior — best-effort text fallback
**Options considered:**
- A. Return `("", tokens)` if no `result` event is seen.
- B. Concatenate `assistant.message.content[*].text` blocks as a fallback.

**Chosen approach:** B (per spec FR-3).

**Rationale:** Downstream consumers (artifact upload, review parsing) prefer non-empty text where available. Cost is trivial — we already iterate every line. The fallback only fires on truncation, never on the happy path.

#### Decision 4: Silent-skip on parse failure / missing `usage`
**Options considered:**
- A. Raise on the first malformed line.
- B. Log WARN, continue.
- C. Skip silently (DEBUG at most).

**Chosen approach:** C.

**Rationale:** The dispatcher relies on `_parse_json_output` succeeding to advance feature state (NFR-2). A worker crash on a partial line would halt the pipeline; an undercounted token total only affects cost telemetry. WARN-level logs would create noise on every run because real streams sporadically truncate.

## Implementation Guidance

### Directory / Module Structure

No new files in `agentharness/`. Modify in place:

```
agentharness/
  agent_runner.py          ← rewrite _parse_json_output (lines 188–224)
tests/
  test_agent_runner_parse.py  ← NEW: 7 unit tests per spec FR-5
```

Do **not** create a new `parser.py` module — the function is small, has one caller, and lives correctly next to its only consumer. KISS / YAGNI.

### Interfaces and Contracts

**Existing signature is preserved** (note: it takes `agent_id` too — the spec's signature is slightly off and must be honored as-is):

```python
def _parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]:
    ...
```

**Stream event shapes consulted (read-only):**

| Event type | Field consumed | Purpose |
|------------|----------------|---------|
| `assistant` | `message.usage.input_tokens` | sum |
| `assistant` | `message.usage.output_tokens` | sum |
| `assistant` | `message.usage.cache_creation_input_tokens` | sum (→ `TokenUsage.cache_creation_tokens`) |
| `assistant` | `message.usage.cache_read_input_tokens` | sum (→ `TokenUsage.cache_read_tokens`) |
| `assistant` | `message.content[*].text` (where `type=="text"`) | best-effort text on truncation only |
| `result`   | `result` (string) | final text |

All other event types (`system`, `user`, `tool_result`) are ignored.

**`TokenUsage` field-name mapping (CRITICAL, see Spec Amendment 1):** Source NDJSON uses `cache_creation_input_tokens` and `cache_read_input_tokens`; the model uses `cache_creation_tokens` and `cache_read_tokens`. The aggregator must translate.

**Return contract:**

| Condition | Return |
|-----------|--------|
| Empty / non-JSON `raw` (no parseable lines) | `(raw, None)` |
| Parsed events but `tokens.total == 0` | `(text, None)` |
| Truncated stream (no `result` event) | `(best_effort_text, tokens or None)` |
| Happy path | `(result_text, tokens)` |

`tokens.total` must mean the same thing it does today — sum of `input_tokens + output_tokens` (per `models.py:50`). Cache fields are accumulated but do not gate the "zero total" exit branch.

### Data Flow

**Happy path — developer task with implementer + reviewer subagents:**

```
1. claude -p starts, emits NDJSON stream.
2. Subagent (implementer) Task tool:
   {"type":"assistant", "message":{"usage":{"input_tokens":12000, ...}}}
3. Subagent (reviewer) Task tool:
   {"type":"assistant", "message":{"usage":{"input_tokens":18000, ...}}}
4. Parent assistant final turn:
   {"type":"assistant", "message":{"usage":{"input_tokens":1, "output_tokens":16000, ...}}}
5. Final:
   {"type":"result", "result":"## Status: DONE\n..."}
6. _parse_json_output sums (1)+(2)+(3)+(4) → tokens = 30001 in / Σout
7. Returns (event[5].result, tokens) → run_task stores in TaskEntry.tokens_used
8. state.json reflects true parent + subagent total
```

**Malformed-line path:** `try: json.loads(line) except JSONDecodeError: continue`. Aggregation continues with surrounding events.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Claude Code emits sidechain usage in a future shape (e.g., nested under a different key) | MEDIUM | Aggregator is shape-tolerant: missing `message.usage` → 0 contribution, no raise. Ship with logging at DEBUG so a future drift is observable without crashing. |
| `result.usage` and the parent assistant's `message.usage` double-count (i.e., final `result.usage` is the parent's last-turn usage *re-emitted*) | LOW | We deliberately ignore `result.usage` and only sum `assistant.message.usage`. No double-count possible. |
| `result.result` field type changes (object instead of string) | LOW | Read with `event.get("result", "")` and ensure callers tolerate any non-`str` (already do — they pass through to artifacts). Add a defensive `str(...)` cast if non-str surfaces. |
| Large streams (≫10k lines) make per-line `json.loads` measurable | LOW | Single pass, stdlib `json` is fast enough; agent runtime dominates by orders of magnitude. NFR-1 explicitly accepts this. |
| Test brittleness due to hand-crafted NDJSON fixtures drifting from real Claude Code output | MEDIUM | Capture one real `claude -p --output-format stream-json` sample (see Prerequisites) and check it into `tests/fixtures/agent_streams/` for at least one of the seven tests. |
| Loss of legacy `total_*_tokens` field reading (older Claude Code shape) | LOW | Confirm via captured fixture that today's Claude Code emits `assistant.message.usage` for **parent** turns. If older shapes lacking that block exist on supported versions, fall back to `result.total_*_tokens` only when no `assistant.message.usage` was seen. |
| Concurrent observer task writes — unrelated, but worth noting | LOW | Out of scope. State writes already serialized via blob lease / GitHub label updates. |

## Specification Amendments

1. **Field-name mapping is implicit in the spec but must be explicit in implementation.** The NDJSON stream uses `cache_creation_input_tokens` / `cache_read_input_tokens`; `TokenUsage` exposes them as `cache_creation_tokens` / `cache_read_tokens`. Implementation must translate; the spec's "Stream event shapes consulted" section names the source fields but does not call out the mapping.

2. **Function signature in spec is incomplete.** Spec FR-4 cites `_parse_json_output(raw: str) -> tuple[str, TokenUsage | None]`, but the actual signature is `(raw: str, agent_id: str)` — `agent_id` is used for the existing `log.warning("Agent %r: ...")` on non-JSON input. Preserve the two-arg signature.

3. **Parent-assistant-only legacy fallback.** If a captured fixture shows older Claude Code versions where parent token usage *only* appears in `result.total_input_tokens` etc. and not in any `assistant.message.usage`, add a fallback: when the aggregated total is zero **and** a `result` event with `total_*_tokens` is present, populate `TokenUsage` from those fields. The current spec drops this path (it relies on `assistant.message.usage` being universal); add it only if the captured fixture shows it's needed.

4. **Truncated-stream "best-effort text" definition.** Spec says concatenate `assistant.message.content[*]` text blocks. Clarify: take the **last** assistant event's text only (not all events concatenated), to avoid producing a multi-megabyte string from a chatty run.

5. **DEBUG logging on skip.** Spec NFR-4 says malformed lines "may be logged at DEBUG". Make this a SHOULD: emit one DEBUG line per skipped malformed line and one DEBUG line summarizing aggregation (e.g., `parsed N events, M assistant turns, tokens=...`) — invaluable for the post-deploy live check called for in `brief.md`'s Verification section.

## Prerequisites

1. **Capture a real stream-json fixture** from a current developer run that fans out to subagents, save to `tests/fixtures/agent_streams/developer_with_subagents.ndjson`. Use it for test #3 (multiple sidechains). This anchors the parser to actual Claude Code output rather than a synthetic guess.

2. **Verify `assistant.message.usage` shape on the team's pinned Claude Code version.** A quick `claude --version` check; if the version differs from what the spec author observed, capture a fresh fixture before implementing. Document the captured version in a top-of-file comment in the fixture file.

3. **No infra, no migrations, no config changes.** `state.json` schema is unchanged; old runs keep their (undercounted) totals — explicit non-goal in the brief.

4. **Pytest setup is already in place** (`pyproject.toml`, `.venv/bin/pytest`); no test infrastructure work needed.