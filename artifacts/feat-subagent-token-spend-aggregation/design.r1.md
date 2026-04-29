```markdown
# Design: Subagent Token Spend Aggregation

## Component Design

### `_parse_json_output` (rewrite in `agentharness/agent_runner.py:188–224`)

**Responsibility:** Translate the full NDJSON stdout buffer from `claude -p --output-format stream-json` into `(text, TokenUsage | None)`, aggregating token usage from every `assistant` event rather than reading only the final `result` event.

**Current behavior (to replace):**
- Tries `json.loads(entire_blob)` — fails on NDJSON.
- Falls back to parsing the last non-empty line (`result` event).
- Reads tokens from `result.usage` / `result.total_*_tokens` — misses sidechain spend.

**New behavior:**
Single forward pass over `raw.splitlines()` with two accumulators:

| Accumulator | Type | Updated when |
|---|---|---|
| `tokens` | `TokenUsage` | Each `assistant` event with `message.usage` present |
| `result_text` | `str` | Each `result` event (overwrites; last one wins) |
| `last_assistant_text` | `str` | Each `assistant` event's last `content[*].text` block (truncation fallback only) |

**Signature (unchanged):**
```python
def _parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]:
```

**Logic sketch:**
```python
tokens = TokenUsage()
result_text: str | None = None
last_assistant_text = ""
any_json = False

for line in raw.splitlines():
    if not line.strip():
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        log.debug("Agent %r: skipping malformed line", agent_id)
        continue
    any_json = True

    if event.get("type") == "assistant":
        usage = (event.get("message") or {}).get("usage") or {}
        tokens = tokens + TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        )
        # capture last assistant text for truncation fallback
        content = (event.get("message") or {}).get("content") or []
        texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
        if texts:
            last_assistant_text = texts[-1]

    elif event.get("type") == "result":
        result_text = str(event.get("result", ""))

if not any_json:
    log.warning("Agent %r: output is not JSON, treating as plain text", agent_id)
    return raw, None

text = result_text if result_text is not None else last_assistant_text
log.debug("Agent %r: parsed N assistant turns, tokens=%s", agent_id, tokens)
return (text, tokens) if tokens.total > 0 else (text, None)
```

**Key field-name translation (NDJSON → `TokenUsage`):**

| Stream field | `TokenUsage` field |
|---|---|
| `cache_creation_input_tokens` | `cache_creation_tokens` |
| `cache_read_input_tokens` | `cache_read_tokens` |

No other callers change. `run_agent` at line 106 receives the corrected `RunResult.tokens` automatically.

---

### `tests/test_agent_runner_parse.py` (new file)

**Responsibility:** Unit-test `_parse_json_output` in isolation using synthetic NDJSON fixtures. Imports `_parse_json_output` directly (white-box test of a private function — acceptable given it is the sole locus of this fix).

Seven named test functions (one-to-one with FR-5):

| Test name | Scenario |
|---|---|
| `test_single_parent_assistant_and_result` | One `assistant` event + `result` → tokens = that block |
| `test_parent_plus_one_sidechain` | Parent + one sidechain `assistant` → tokens = sum of both |
| `test_multiple_sidechains` | Parent + implementer + reviewer → sum across all four fields |
| `test_malformed_line_interleaved` | Bad JSON line between valid events → bad line skipped, others counted |
| `test_truncated_stream_no_result` | No `result` event → tokens aggregated; text = last assistant content |
| `test_empty_non_json_output` | No parseable JSON lines → `(raw, None)` |
| `test_zero_usage_total` | All `assistant.usage` fields zero → `(text, None)` |

Optional fixture file (per arch-review prerequisite): `tests/fixtures/agent_streams/developer_with_subagents.ndjson` — a real captured stream, used by `test_multiple_sidechains` as the definitive regression anchor.

---

## Data Schemas

### Stream event shapes consumed (read-only)

```jsonc
// assistant event — token aggregation source
{
  "type": "assistant",
  "message": {
    "usage": {
      "input_tokens": 12000,
      "output_tokens": 800,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 4096
    },
    "content": [
      { "type": "text", "text": "…" }
    ]
  }
}

// result event — final text source
{
  "type": "result",
  "result": "## Status: DONE\n…"
}

// ignored event types
{ "type": "system", … }
{ "type": "user", … }
{ "type": "tool_result", … }
```

### `TokenUsage` (existing, unchanged)

```python
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0   # ← from cache_creation_input_tokens
    cache_read_tokens: int = 0       # ← from cache_read_input_tokens

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens   # gates None return

    def __add__(self, other: TokenUsage) -> TokenUsage: ...  # field-wise sum
```

### Return contract

| Condition | Returned `(text, usage)` |
|---|---|
| No parseable JSON lines | `(raw, None)` |
| Parsed events, `tokens.total == 0` | `(text, None)` |
| Truncated stream (no `result` event) | `(last_assistant_text or "", tokens \| None)` |
| Happy path | `(result_event["result"], tokens)` |
```