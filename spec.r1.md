# Specification: Product Agent — Analyst Open Questions Loop

## Summary

Introduce a new product agent (Opus model) that closes the gap between the analyst's open questions and the rest of the pipeline. When the analyst emits a spec containing unresolved questions, the product agent answers them autonomously and the analyst re-runs with the answers folded in. The loop is bounded by a configurable iteration cap; if the analyst signals completion (no questions), the product agent is bypassed entirely.

## Background

The analyst agent currently produces a `## Open Questions` section in `spec.rN.md` listing anything the brief left ambiguous. Today these questions are inert — the dispatcher transitions directly from `analyzing` to `architecting`, and downstream agents (architect, designer, planner, developers) silently absorb the ambiguity and make their own assumptions. This produces designs and implementations that drift from user intent.

The product agent fills that gap. It is invoked only when the analyst flags unresolved questions, answers them with authoritative judgment grounded in codebase context, and feeds the answers back into a fresh analyst run. The result is a clean spec with no open questions handed to the architect — without burning Opus tokens on briefs that are already complete.

Two principles guide the design:

1. **Conditional cost** — Opus runs only when questions exist.
2. **Bounded loop** — a cap (`max_analyst_iterations`) guarantees forward progress even if the analyst keeps surfacing new questions.

## Functional Requirements

### FR-1: Analyst Status Signal

The analyst agent must terminate its output with exactly one status line of the form:

```
## Status: COMPLETE
```
or
```
## Status: HAS_QUESTIONS
```

`HAS_QUESTIONS` is emitted when the spec's `## Open Questions` section contains at least one question. `COMPLETE` is emitted when the section is empty, contains only "None.", or is absent entirely.

A new dispatcher helper `_parse_analyst_status(output: str) -> Literal["COMPLETE", "HAS_QUESTIONS"]` extracts the signal. Parsing rules:

- Search for `## Status:` line (case-sensitive, leading anchor matches `^## Status:`)
- Trim surrounding whitespace from the captured value
- Treat `HAS_QUESTIONS` as the only positive trigger; any other value (including missing line) defaults to `COMPLETE`

**Acceptance criteria:**
- Analyst output without a `## Status:` line is parsed as `COMPLETE` (safe default — proceed to architect)
- Analyst output with `## Status: HAS_QUESTIONS` parses as `HAS_QUESTIONS`
- Analyst output with `## Status: COMPLETE` parses as `COMPLETE`
- Parser is case-sensitive on the status keywords; lowercase or mixed-case is treated as `COMPLETE`
- The analyst's system prompt is updated to require the status line and document the contract
- Existing analyst output snapshots in tests are updated to include the status line

### FR-2: Conditional Product Agent Dispatch

After an `analyzing` task completes, `dispatch_after_completion` decides the next state by parsing the analyst's status and consulting the iteration counter:

| Status | Iterations check | Next state | Action |
|---|---|---|---|
| `COMPLETE` | n/a | `architecting` | Standard linear transition (unchanged behavior) |
| `HAS_QUESTIONS` | `current_analyst_iteration < max_analyst_iterations` | `questioning` | Enqueue product agent on `product-queue` |
| `HAS_QUESTIONS` | `current_analyst_iteration >= max_analyst_iterations` | `architecting` | Cap reached — proceed with current spec; log warning |

The branching replaces the existing `_LINEAR_TRANSITIONS["analyzing"] = "architecting"` entry with a dedicated handler in `dispatch_after_completion`.

**Acceptance criteria:**
- When the analyst signals `COMPLETE`, the product agent is never enqueued, even if a stale `## Open Questions` section is present in the spec body
- When the cap is reached, the dispatcher unconditionally transitions to `architecting` and emits a structured log entry containing `feature_id`, `current_analyst_iteration`, and `max_analyst_iterations`
- `current_analyst_iteration` increments on each `questioning → analyzing` transition (i.e., when the analyst re-runs), not when the analyst first runs
- The `analyzing → architecting` transition path remains atomic with respect to state writes — no intermediate state where the feature has both `analyzing` complete and no next dispatch

### FR-3: Product Agent Definition

A new agent file `.agents/product.md` with frontmatter:

```yaml
---
id: product
display_name: "Product Agent"
model: claude-opus-4-7
phase: questioning
max_turns: 1
allowed_tools: []
output_format: markdown
visibility_timeout: 300
retry_limit: 3
output_parsing: none
output_file_glob: answers.md
context_files: []
---
```

System prompt responsibilities:

1. Identify the latest `spec.r{N}.md` in the input artifacts.
2. Locate the `## Open Questions` section.
3. For each question, produce a structured answer with:
   - The question (verbatim, as a `### Question {n}` heading)
   - A direct, authoritative answer (the agent must commit to a decision, not hedge)
   - Brief rationale (1–3 sentences)
4. Emit no other content — the output is purely a list of answers.

The agent reads `brief.md`, the latest `spec.r{N}.md`, and any prior `answers.r{M}.md` files (passed via `_artifacts_for_phase`) so it does not contradict earlier answers.

**Acceptance criteria:**
- File `.agents/product.md` exists with the frontmatter above
- Agent output is uploaded to `artifacts/{feature_id}/answers.r{N}.md` where `{N}` matches the analyst iteration number that emitted the questions
- `output_file_glob: answers.md` is mapped through `prompt_builder` / `run_task.py` to the revision-named artifact `answers.r{N}.md`
- `.pipeline/config.json` gains a `product-queue` entry mapping to the `product` agent ID
- Queue setup for the GitHub backend requires no manual action; for the Azure backend, the `/azure-storage` skill must be able to provision `product-queue`
- The system prompt explicitly forbids the agent from leaving questions unanswered ("if a question cannot be definitively answered, choose the most reasonable default and document the rationale")

### FR-4: Analyst Re-Run With Accumulated Context

After the product agent completes (`questioning` → `analyzing`), the dispatcher enqueues a new analyst task carrying the full artifact history:

- `brief.md`
- Every prior `spec.r1.md` … `spec.rN.md`
- Every prior `answers.r1.md` … `answers.rN.md`

The analyst's system prompt is updated to instruct it:

1. Read all `answers.r{M}.md` files in ascending revision order.
2. Apply every answer to the spec — modify or remove the corresponding question and update affected sections.
3. Produce the next spec revision (`spec.r{N+1}.md`) with `## Open Questions` empty (or carrying only genuinely new questions surfaced by the answers themselves).
4. Emit the appropriate `## Status:` line (FR-1).

The mapping update for `_artifacts_for_phase("analyzing", state)` returns:

```python
[
    "brief.md",
    *[f"spec.r{i}.md" for i in range(1, current_analyst_iteration + 1)],
    *[f"answers.r{i}.md" for i in range(1, current_analyst_iteration + 1)],
]
```

(Only artifacts that exist on the backend are passed through; missing files are skipped silently to keep the helper resilient to partial state.)

**Acceptance criteria:**
- The analyst re-run prompt includes all prior specs and all prior answer files, not just the most recent
- A revised spec produced after a product-agent answer for every prior question has `## Open Questions` empty or absent
- The analyst correctly emits `## Status: COMPLETE` when no questions remain, breaking the loop
- If the analyst introduces a new question in `r{N+1}` (e.g., follow-up clarification triggered by an answer), the loop continues until the cap
- The artifact upload logic preserves the analyst's existing single-output `spec.md` → `spec.r{N+1}.md` revision mapping; no special casing is needed for re-runs

### FR-5: Iteration Cap and Configuration

`FeatureStateConfig` (Pydantic model in `models.py`) gains two fields:

```python
class FeatureStateConfig(BaseModel):
    max_analyst_iterations: int = 2
    current_analyst_iteration: int = 0
    # ... existing fields
```

`config.py` reads the limit from `.pipeline/config.json`:

```json
{
  "storage_backend": "github",
  "max_analyst_iterations": 2,
  ...
}
```

Default when the key is absent: `2`. Validation: `max_analyst_iterations >= 0`. A value of `0` disables the loop entirely (analyst always proceeds to architect, ignoring questions).

`current_analyst_iteration` is initialized to `0` when the feature is created and incremented atomically inside the dispatcher's state update closure (within the existing lease-protected `state_manager.update()` call) on every `questioning → analyzing` transition.

**Acceptance criteria:**
- Default `max_analyst_iterations` is `2` if the key is absent from `config.json`
- Setting `max_analyst_iterations: 0` causes the dispatcher to skip the product agent entirely (treat all `HAS_QUESTIONS` outcomes as if cap was reached)
- The counter increments atomically — no race condition between concurrent observers reading and writing the value
- Counter is persisted in `state.json` (Azure) or issue body (GitHub) and survives observer restarts
- TUI surfaces both `current_analyst_iteration` and `max_analyst_iterations` in the feature detail view

### FR-6: New State and Queue

`FeatureStatus` enum (in `models.py`) gains a new value `questioning`. The state machine becomes:

```
brainstorming
  → analyzing
      → [COMPLETE]                  → architecting → designing → planning → developing → reviewing → done
      → [HAS_QUESTIONS, iter < max] → questioning  → analyzing (iter++)
      → [HAS_QUESTIONS, iter >= max] → architecting → ...
```

`failed` is reachable from any state on retry exhaustion (unchanged).

`STATE_TO_QUEUE` mapping:

```python
STATE_TO_QUEUE = {
    FeatureStatus.analyzing: "analyst-queue",
    FeatureStatus.questioning: "product-queue",  # NEW
    FeatureStatus.architecting: "architect-queue",
    # ... unchanged below
}
```

**Acceptance criteria:**
- `FeatureStatus.questioning` is a valid enum value and is serialized/deserialized correctly across both backends
- `product-queue` is registered in `.pipeline/config.json` with appropriate `visibility_timeout` (default 300s, matching agent definition)
- The TUI's status filter and progress bar render `questioning` correctly; unknown-status fallback path is not triggered

### FR-7: Dispatcher Changes Summary

| Location | Change |
|---|---|
| `_LINEAR_TRANSITIONS` | Remove `"analyzing": "architecting"` entry — branching logic replaces it |
| `STATE_TO_QUEUE` | Add `FeatureStatus.questioning: "product-queue"` |
| `dispatch_after_completion` | New `analyzing` branch: parse status (FR-1), check cap (FR-5), dispatch to product or architect |
| `dispatch_after_completion` | New `questioning` branch: increment `current_analyst_iteration`, re-enqueue analyst |
| `_parse_analyst_status` | New helper (FR-1) |
| `build_phase_task` | Handle `questioning` phase; handle `analyzing` re-runs with accumulated artifact list |
| `_artifacts_for_phase` | Update `analyzing` entry to include all prior `spec.r{N}.md` and `answers.r{N}.md` files |

**Acceptance criteria:**
- All seven dispatcher modifications land in a single coherent change set
- Existing dispatcher tests for the `analyzing → architecting` happy path continue to pass (covering the `COMPLETE` case)
- New tests cover: `HAS_QUESTIONS` under cap, `HAS_QUESTIONS` at cap, missing status line, malformed status line, counter increment on re-run

## Non-Functional Requirements

### NFR-1: Transparency

- The `questioning` phase is visible in the Textual TUI alongside other phases (status badge, color-coded entry).
- Each loop iteration appears as a distinct phase entry: `analyzing r1`, `questioning r1`, `analyzing r2`, `questioning r2`, etc.
- Log lines emitted by the dispatcher on cap-reached include the iteration count and a clear "cap reached" marker for grep-friendly debugging.

### NFR-2: Cost Control

- The product agent (Opus) is invoked **only** when the analyst signals `HAS_QUESTIONS`. A brief that produces a complete spec on the first pass costs zero Opus tokens.
- The iteration cap (`max_analyst_iterations`, default 2) bounds the worst-case cost: at most `cap × (analyst + product)` invocations per feature.
- A cap value of `0` provides an emergency kill switch (disable Opus entirely) without a code change.

### NFR-3: Backwards Compatibility

- Features created before this change have `current_analyst_iteration` defaulting to `0` on first read (Pydantic default fills missing field).
- Existing analyst output without a `## Status:` line is treated as `COMPLETE` — no in-flight feature breaks during deployment.
- The new `questioning` enum value is additive; existing `FeatureStatus` deserialization paths must not error on the new value.

### NFR-4: Performance

- The product agent's `visibility_timeout` is 300s (5 min) — sufficient for an Opus call answering up to ~20 questions, conservative enough to recover quickly from observer failures.
- The analyst re-run with accumulated artifacts increases prompt size linearly with iteration count. With `max_analyst_iterations = 2`, worst-case payload at iteration 3 is `brief + 2 specs + 2 answers` — well within model context limits for typical specs (under 50KB total).

### NFR-5: Idempotency and Recovery

- Re-running a `questioning` task (e.g., after observer crash) produces the same `answers.r{N}.md` revision number — no duplicate `r1.md` and `r2.md` for the same iteration.
- The atomic increment of `current_analyst_iteration` happens inside the state update lease, ensuring exactly-once semantics across observer restarts.

## Data Model

### `FeatureStateConfig` (additive fields)

```python
class FeatureStateConfig(BaseModel):
    max_analyst_iterations: int = Field(default=2, ge=0)
    current_analyst_iteration: int = Field(default=0, ge=0)
    # ... existing fields preserved
```

### `FeatureStatus` (additive enum value)

```python
class FeatureStatus(str, Enum):
    brainstorming = "brainstorming"
    analyzing = "analyzing"
    questioning = "questioning"  # NEW
    architecting = "architecting"
    designing = "designing"
    planning = "planning"
    developing = "developing"
    reviewing = "reviewing"
    dev_revision = "dev_revision"
    done = "done"
    failed = "failed"
```

### Artifact layout

```
artifacts/{feature_id}/
  brief.md
  spec.r1.md          # first analyst pass
  answers.r1.md       # product agent — iteration 1 (only if HAS_QUESTIONS)
  spec.r2.md          # analyst re-run — iteration 2
  answers.r2.md       # product agent — iteration 2 (only if still HAS_QUESTIONS)
  spec.r{N}.md        # final clean spec — handed to architect onward
  arch-review.r1.md   # downstream artifacts unchanged
  ...
```

The "current spec" handed to architect/designer/planner/developer is always the highest-revision `spec.r{N}.md` present.

### Queue registration

`.pipeline/config.json`:

```json
{
  "queues": {
    "analyst-queue": {"agent": "analyst", "visibility_timeout": 600},
    "product-queue": {"agent": "product", "visibility_timeout": 300},
    "architect-queue": {"agent": "architect", "visibility_timeout": 600},
    ...
  },
  "max_analyst_iterations": 2
}
```

## API / Interface Design

### Internal interfaces

**`dispatcher._parse_analyst_status(output: str) -> Literal["COMPLETE", "HAS_QUESTIONS"]`**
- Mirrors existing `_parse_developer_status` shape
- Returns `"COMPLETE"` as safe default

**`dispatcher.dispatch_after_completion(state: FeatureState, completed_phase: FeatureStatus, output: str) -> None`** (existing signature, new branches)
- `analyzing` branch:
  ```python
  status = _parse_analyst_status(output)
  if status == "COMPLETE":
      transition_to(architecting)
  elif state.config.current_analyst_iteration < state.config.max_analyst_iterations:
      transition_to(questioning)  # enqueue product agent
  else:
      log.warning("max_analyst_iterations cap reached", ...)
      transition_to(architecting)
  ```
- `questioning` branch:
  ```python
  state.config.current_analyst_iteration += 1
  transition_to(analyzing)  # re-enqueue analyst with accumulated artifacts
  ```

**`dispatcher._artifacts_for_phase(phase: FeatureStatus, state: FeatureState) -> list[str]`**
- For `analyzing`: returns `["brief.md"] + all prior spec.rN.md + all prior answers.rN.md`
- For `questioning`: returns `["brief.md", latest_spec.md] + all prior answers.rN.md`

### CLI / TUI

- No new CLI commands.
- TUI feature detail view gains an "Analyst iterations" line: `2 / 2 (cap reached)` or `1 / 2`.
- TUI phase log shows `questioning r1`, `analyzing r2`, etc., as distinct entries.

### Agent prompt contracts

**Analyst** — system prompt addition:
```
At the very end of your output, emit exactly one of:
  ## Status: COMPLETE        (when ## Open Questions is empty or absent)
  ## Status: HAS_QUESTIONS   (when ## Open Questions has at least one question)

If you receive answers.rN.md files in your input, read every one in ascending
order and apply each answer to your revised spec before producing it.
```

**Product** — full system prompt:
```
You answer open questions in a feature spec. You will receive:
  - brief.md
  - The latest spec.rN.md (containing ## Open Questions)
  - Any prior answers.rM.md (do not contradict earlier answers)
  - Project context files

For each question in ## Open Questions:
  ### Question {n}
  {verbatim question}

  **Answer:** {direct, decisive answer}

  **Rationale:** {1-3 sentences}

Output only the list of answered questions. No preamble, no summary.
If a question cannot be definitively answered, choose the most reasonable
default and document the rationale.
```

## Dependencies

- **Existing**: `dispatcher.py`, `models.py`, `config.py`, `prompt_builder.py`, `run_task.py`, `tui.py`, `.pipeline/config.json`, `.agents/analyst.md`
- **External**: Anthropic Claude API access for `claude-opus-4-7` model (already available; same auth as other agents)
- **Backend-specific**: For Azure backend, `product-queue` must be provisioned via `/azure-storage` skill or CLI. For GitHub backend, no infrastructure setup needed (issues created on demand).
- **No new Python packages required.**

## Out of Scope

- Product agent interacting with the user directly — it answers autonomously based on brief, spec, and codebase context.
- Product agent reading external sources beyond the spec, brief, prior answer files, and configured `context_files`.
- Retroactively re-running the product agent on existing/in-flight features that pre-date this change.
- Per-question routing (e.g., escalating specific questions to a human, splitting questions across multiple agents).
- Confidence scoring or selective re-asking of low-confidence answers.
- Caching/memoization of product agent answers across features.
- Changing the architect, designer, planner, developer, or reviewer agents — they consume the highest-revision `spec.r{N}.md` exactly as they do today.

## Open Questions

None. (The brief explicitly closes all design questions; the iteration cap default of `2` and Opus model choice for the product agent are fixed by the brief.)

## Status: COMPLETE