# Subagent Token Spend Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `_parse_json_output` in `agentharness/agent_runner.py` so per-task `tokens_used` includes spend from Task-tool subagents (implementer/reviewer fan-out), not just the parent Claude session.

**Architecture:** Replace last-line-only parsing with a single-pass aggregator that walks every line of the `claude -p --output-format stream-json` NDJSON output and sums every `assistant.message.usage` block (parent + sidechains share the same shape). Final text still comes from the `result` event; cache fields are translated from the wire's `*_input_tokens` names to the `TokenUsage` model's `cache_creation_tokens`/`cache_read_tokens`. Truncated streams fall back to the last `assistant` event's text. Malformed lines are skipped silently.

**Tech Stack:** Python 3.11+, stdlib `json`, Pydantic `TokenUsage` model (existing), pytest + pytest-asyncio (existing dev deps). No new dependencies.

---

## File Structure

| File | Role |
|---|---|
| `agentharness/agent_runner.py` (modify lines 188–224) | Rewrite `_parse_json_output` to aggregate all `assistant.message.usage` blocks |
| `tests/test_agent_runner_parse.py` (create) | Unit tests covering all seven scenarios from spec FR-5 |
| `tests/fixtures/agent_streams/` (create dir + README only) | Documented home for optionally-captured real streams (not populated in this plan) |

No other files change. Callers of `_parse_json_output` (`run_agent` at line 106) are unmodified — return contract `tuple[str, TokenUsage | None]` is preserved.

---

## Task 1: Test scaffolding + first failing test (single parent assistant + result)

**Goal:** Stand up the test file with shared NDJSON helpers, write the simplest passing-by-design test, watch it FAIL under the current parser, then put a minimal aggregator in place that makes only this test pass.

**Files:**
- Create: `tests/test_agent_runner_parse.py`
- Modify: `agentharness/agent_runner.py:188-224` (rewrite `_parse_json_output`)

- [ ] **Step 1: Create `tests/test_agent_runner_parse.py` with helpers and the first test**

```python
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
```

- [ ] **Step 2: Run the new test to confirm it FAILS under the current parser**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_single_parent_assistant_and_result -v`

Expected: FAIL. Current parser fallbacks to the last line (the `result` event), reads `result.total_input_tokens` → 0 and `result.usage` → absent → 0 input/output tokens. The assertion `tokens == TokenUsage(input_tokens=100, output_tokens=50, cache_read_tokens=10)` fails (the function returns `(text, None)` because `tokens.total == 0`).

If by chance it passes, the test was written wrong — re-check that no `total_*_tokens` fields are set on the synthesized `result` event.

- [ ] **Step 3: Rewrite `_parse_json_output` to aggregate every assistant event**

Replace lines 188–224 of `agentharness/agent_runner.py` (the entire current function body) with the new implementation. Open the file and overwrite the function:

```python
def _parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]:
    """Parse claude --output-format stream-json stdout.

    Walks every NDJSON line, summing `assistant.message.usage` across parent and
    sidechain (Task subagent) turns. Final text is taken from the `result` event;
    on truncation, falls back to the last `assistant` event's text content.

    Returns:
        (text, usage):
            text  — final result text, or best-effort assistant content if truncated.
            usage — aggregated TokenUsage across parent + all sidechain assistant
                    events, or None if no parseable JSON lines or zero total.
    """
    if not raw.strip():
        return "", None

    tokens = TokenUsage()
    result_text: str | None = None
    last_assistant_text = ""
    any_json = False
    assistant_turns = 0

    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.debug("Agent %r: skipping malformed stream line", agent_id)
            continue
        any_json = True

        event_type = event.get("type")
        if event_type == "assistant":
            assistant_turns += 1
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            tokens = tokens + TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            )
            content = message.get("content") or []
            texts = [
                b.get("text", "")
                for b in content
                if b.get("type") == "text" and b.get("text")
            ]
            if texts:
                last_assistant_text = texts[-1]

        elif event_type == "result":
            result_text = str(event.get("result", ""))

    if not any_json:
        log.warning("Agent %r: output is not JSON, treating as plain text", agent_id)
        return raw, None

    text = result_text if result_text is not None else last_assistant_text
    log.debug(
        "Agent %r: parsed %d assistant turns, tokens=in=%d out=%d cache_c=%d cache_r=%d",
        agent_id,
        assistant_turns,
        tokens.input_tokens,
        tokens.output_tokens,
        tokens.cache_creation_tokens,
        tokens.cache_read_tokens,
    )

    if tokens.total == 0:
        return text, None
    return text, tokens
```

- [ ] **Step 4: Run the test again to confirm it PASSES**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_single_parent_assistant_and_result -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_runner_parse.py agentharness/agent_runner.py
git commit -m "feat: aggregate token spend across all assistant stream events

Replaces last-line-only parsing of claude -p stream-json with a
single-pass aggregator that sums every assistant.message.usage block
(parent + Task-subagent sidechains share the same shape). Cache
field names are translated from the wire's *_input_tokens to the
TokenUsage model's cache_*_tokens.

First passing test: single parent assistant + result event."
```

---

## Task 2: Sidechain regression test (parent + one subagent turn)

**Goal:** Lock in the actual fix this feature was opened for — sidechain (Task subagent) usage must be summed into the per-task total.

**Files:**
- Modify: `tests/test_agent_runner_parse.py` (append one test)

- [ ] **Step 1: Append the sidechain test**

```python
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
```

- [ ] **Step 2: Run the test to confirm it PASSES**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_parent_plus_one_sidechain -v`

Expected: PASS. The aggregator from Task 1 already sums every assistant event, so no implementation change is needed — this test verifies that property.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: regression for sidechain (subagent) token aggregation"
```

---

## Task 3: Multi-sidechain test covering all four token fields

**Goal:** Verify the implementer + reviewer fan-out shape (the real production case) and that **all four** token fields — including the cache fields whose names are translated from the wire format — sum correctly.

**Files:**
- Modify: `tests/test_agent_runner_parse.py`

- [ ] **Step 1: Append the multi-sidechain test**

```python
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
```

- [ ] **Step 2: Run the test to confirm it PASSES**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_multiple_sidechains -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: cover multi-sidechain fan-out and cache field translation"
```

---

## Task 4: Malformed-line tolerance

**Goal:** Verify a JSON-decode-error line interleaved with valid events does not raise and does not stop aggregation of surrounding events.

**Files:**
- Modify: `tests/test_agent_runner_parse.py`

- [ ] **Step 1: Append the malformed-line test**

```python
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
```

- [ ] **Step 2: Run the test to confirm it PASSES**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_malformed_line_interleaved -v`

Expected: PASS. The aggregator's `try/except json.JSONDecodeError: continue` from Task 1 handles this.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: malformed JSON lines are skipped, aggregation continues"
```

---

## Task 5: Truncated stream falls back to last assistant text

**Goal:** Verify that when the stream ends without a `result` event (e.g., process killed, timeout, partial buffer), tokens are still aggregated and `text` is the last assistant event's last text block (per arch-review amendment 4 — last only, not concatenated).

**Files:**
- Modify: `tests/test_agent_runner_parse.py`

- [ ] **Step 1: Append the truncated-stream test**

```python
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
```

- [ ] **Step 2: Run the test to confirm it PASSES**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_truncated_stream_no_result -v`

Expected: PASS. The aggregator updates `last_assistant_text` to each assistant event's last text block; since `result_text` stays `None`, the function returns `last_assistant_text`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: truncated stream returns aggregated tokens with best-effort text"
```

---

## Task 6: Empty / non-JSON output preserves legacy contract

**Goal:** Confirm the existing return contract `(raw, None)` for plain (non-JSON) output is preserved — callers like `agent_runner` rely on this when an agent failed to emit valid stream-json.

**Files:**
- Modify: `tests/test_agent_runner_parse.py`

- [ ] **Step 1: Append the non-JSON test**

```python
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
```

- [ ] **Step 2: Run both tests to confirm they PASS**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_empty_non_json_output tests/test_agent_runner_parse.py::test_empty_string_input -v`

Expected: PASS for both. The aggregator's `if not any_json` branch returns `(raw, None)`; the empty-input early-return handles the empty-string case.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: non-JSON and empty output preserve legacy return contract"
```

---

## Task 7: Zero-usage exit branch

**Goal:** Confirm that when JSON events parse but every assistant `usage` block is zero (or missing), the function returns `(text, None)` so callers skip storing an empty `TokenUsage` — matching the design's gating on `tokens.total == 0`.

**Files:**
- Modify: `tests/test_agent_runner_parse.py`

- [ ] **Step 1: Append the zero-usage test and the missing-usage test**

```python
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
```

- [ ] **Step 2: Run both tests to confirm they PASS**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py::test_zero_usage_total tests/test_agent_runner_parse.py::test_assistant_event_missing_usage_block -v`

Expected: PASS for both. The `if tokens.total == 0` guard returns `(text, None)`; missing `message.usage` resolves to `{}` via `.get(...) or {}` and contributes zeros.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_runner_parse.py
git commit -m "test: zero-usage and missing-usage cases return (text, None)"
```

---

## Task 8: Captured-fixture documentation + full-suite regression

**Goal:** Document where a real captured `claude -p --output-format stream-json` sample should live (per arch-review prerequisite #1), then run the full test suite to verify nothing else regressed.

**Files:**
- Create: `tests/fixtures/agent_streams/README.md`

- [ ] **Step 1: Create the fixture-directory README**

Save to `tests/fixtures/agent_streams/README.md`:

```markdown
# Captured agent stream fixtures

This directory is reserved for real `claude -p --output-format stream-json` captures
used as anchors for parser tests in `tests/test_agent_runner_parse.py`.

## Why

Synthetic NDJSON in the test file matches the documented event shape today, but a
real capture catches drift if Claude Code changes its emission format.

## How to capture

Run a developer task that fans out via the `Task` tool to implementer + reviewer
subagents, redirecting stdout:

```bash
claude -p "<your prompt>" \
  --verbose \
  --model claude-sonnet-4-6 \
  --output-format stream-json \
  --allowedTools bash,read,write \
  > tests/fixtures/agent_streams/developer_with_subagents.ndjson
```

Add a top-of-file comment line in the NDJSON noting the capture date and the
output of `claude --version`. The parser test file may then load and parse the
fixture as an additional assertion.

## Status

Not currently populated. The seven scenarios in `test_agent_runner_parse.py`
use synthetic NDJSON sufficient to exercise every documented branch of
`_parse_json_output`.
```

- [ ] **Step 2: Run the new test file in isolation**

Run: `.venv/bin/pytest tests/test_agent_runner_parse.py -v`

Expected: 9 tests PASS (the 7 named scenarios from spec FR-5 plus the two extras: `test_empty_string_input` and `test_assistant_event_missing_usage_block` added defensively in Tasks 6 and 7).

- [ ] **Step 3: Run the FULL test suite to verify no regressions**

Run: `.venv/bin/pytest tests/ -v`

Expected: All previously-passing tests still pass. In particular, watch for any test that mocked the old shape of `_parse_json_output` — none should exist (the function is private, only called by `run_agent`, and `tests/test_agent_runner_cwd.py` mocks the subprocess, not the parser).

If anything fails, read the failure carefully — the only plausible regression is a test that depended on the legacy reading of `result.total_*_tokens` as the source of truth. The fix is to update that test's NDJSON fixture so usage appears in `assistant.message.usage` (the new source), not on the `result` event.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/agent_streams/README.md
git commit -m "docs: document optional real-stream fixture capture procedure"
```

- [ ] **Step 5: Final sanity check — log the new DEBUG line during a manual smoke**

Run a one-off invocation to make sure the new `log.debug` summary line emits cleanly (does not raise format errors). With `LOG_LEVEL=DEBUG` set, parse a tiny stream:

```bash
.venv/bin/python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from agentharness.agent_runner import _parse_json_output
import json
raw = '\n'.join([
    json.dumps({'type':'assistant','message':{'usage':{'input_tokens':10,'output_tokens':5,'cache_creation_input_tokens':0,'cache_read_input_tokens':0},'content':[{'type':'text','text':'hi'}]}}),
    json.dumps({'type':'result','result':'done'}),
])
print(_parse_json_output(raw, 'developer'))
"
```

Expected: A single DEBUG line of the form `Agent 'developer': parsed 1 assistant turns, tokens=in=10 out=5 cache_c=0 cache_r=0`, then the printed tuple `('done', TokenUsage(input_tokens=10, output_tokens=5, cache_creation_tokens=0, cache_read_tokens=0))`.

No commit for this smoke step — it is a sanity check.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| FR-1 (sum every `assistant.message.usage`) | Tasks 1, 2, 3 |
| FR-2 (text from final `result` event) | Tasks 1, 2, 3 |
| FR-3 case: malformed line | Task 4 |
| FR-3 case: missing `message.usage` | Task 7 (`test_assistant_event_missing_usage_block`) |
| FR-3 case: truncated stream (no `result`) | Task 5 |
| FR-3 case: non-stream-json plain output | Task 6 (`test_empty_non_json_output`) |
| FR-3 case: zero aggregated total | Task 7 (`test_zero_usage_total`) |
| FR-4 (signature unchanged, no caller changes) | Task 1 implementation preserves `(raw: str, agent_id: str) -> tuple[str, TokenUsage \| None]` |
| FR-5 #1 single parent + result | Task 1 |
| FR-5 #2 parent + one sidechain | Task 2 |
| FR-5 #3 multiple sidechains, all 4 fields | Task 3 |
| FR-5 #4 malformed line interleaved | Task 4 |
| FR-5 #5 truncated stream | Task 5 |
| FR-5 #6 empty / non-JSON | Task 6 |
| FR-5 #7 zero usage total | Task 7 |
| NFR-1 single O(n) pass | Task 1 implementation: one `for line in raw.splitlines()` loop |
| NFR-2 silent skip on parse failure / missing fields | Task 1 implementation: `try/except` + `.get(...) or {}` |
| NFR-3 no new dependencies | Task 1 uses only `json` (stdlib) and existing `TokenUsage` |
| NFR-4 logging hygiene (DEBUG, no per-line WARN) | Task 1 implementation: only `log.debug` on skip and summary; `log.warning` retained only for the existing legacy-non-JSON case |
| Arch-review amendment 1 (field-name translation) | Task 1 implementation maps `cache_creation_input_tokens` → `cache_creation_tokens`; Task 3 explicitly asserts this |
| Arch-review amendment 2 (preserve `agent_id` arg) | Task 1 implementation keeps `(raw: str, agent_id: str)` |
| Arch-review amendment 3 (legacy `result.total_*` fallback) | Spec says "rely on `assistant.message.usage` being universal" and the amendment makes the fallback conditional on a captured fixture proving it's needed. Plan does NOT add the fallback — Task 8 documents the capture procedure so a follow-up can add it if drift is observed. This is intentional under YAGNI. |
| Arch-review amendment 4 (truncation: last assistant text only) | Task 1 implementation overwrites `last_assistant_text` per event; Task 5 asserts the LAST event's text is returned. |
| Arch-review amendment 5 (DEBUG logging on skip + summary) | Task 1 implementation emits `log.debug` for both. |
| Arch-review prerequisite 1 (capture real fixture) | Task 8 documents the procedure; the actual capture is left as an optional follow-up since synthetic NDJSON exercises every code path. |

**Placeholder scan:** No "TBD", "TODO", "fill in", or vague "handle errors appropriately" steps. Every code block is the actual content the engineer types. Every `pytest` invocation has the exact node id.

**Type consistency:**
- Function signature is `_parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]` everywhere.
- `TokenUsage` field names: `input_tokens`, `output_tokens`, `cache_creation_tokens`, `cache_read_tokens` — used identically in implementation and every test assertion.
- Wire field names: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` — used in `_assistant_event` helper and in the parser's `usage.get(...)` calls.
- The two name spaces are kept distinct and the translation happens in exactly one place (Task 1, Step 3, the `tokens = tokens + TokenUsage(...)` line).
