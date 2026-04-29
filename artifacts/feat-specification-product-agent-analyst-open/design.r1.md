Now I have a complete picture. Writing the design document.

```markdown
# Design: Product Agent — Analyst Open Questions Loop

## UX/UI Design

### TUI Changes (Textual monitoring interface)

The Textual TUI (`tui.py`) requires three targeted additions — no new screens or interactions.

#### Status icon and colour for `questioning`

```
_STATUS_ICONS[FeatureStatus.questioning] = "◌"   # same glyph as other in-flight phases
_STATUS_COLORS[FeatureStatus.questioning] = "cyan"  # distinct from yellow (developing) and magenta (dev_revision)
```

#### Phase order

`_PHASE_ORDER` gains `"questioning"` inserted after `"analyzing"`:

```
["analyzing", "questioning", "architecting", "designing", "planning", "developing", "reviewing"]
```

The phase progress bar (`_phase_bar`) currently hard-codes `5` slots. Update to `len(_PHASE_ORDER)` and adjust bar width accordingly, or keep truncation at 5 while counting all 7 phases toward filled/in_progress.

#### Feature detail — analyst iteration counter

The `TaskPanel` border title (currently `"Tasks  —  total: {tokens}"`) is extended with an analyst iterations fragment when the feature has entered the `questioning` phase at least once:

```
Tasks  —  total: 12k  —  analyst: 1 / 2
                              ^iteration counter / cap
```

When `current_analyst_iteration == max_analyst_iterations` (cap reached), append `" (cap)"`:

```
Tasks  —  total: 12k  —  analyst: 2 / 2 (cap)
```

When `current_analyst_iteration == 0` (first pass, never looped), omit the analyst fragment entirely to avoid noise on clean briefs.

#### Phase log label format

`_build_task_rows` renders phase rows using the phase string key. When `PhaseInfo.revision > 1`, the phase column label becomes `analyzing r{revision}` and `questioning r{revision}`:

```
analyzing r1  completed  analyst  r1  2m 4s  ↑8k ↓3k
questioning r1  completed  product  r1  1m 12s  ↑5k ↓2k
analyzing r2  in_progress  analyst  r2  0m 30s  ...
```

When revision is `1` (first pass), the label stays plain `analyzing` to preserve existing behaviour.

#### ASCII summary of TUI feature row

```
◌  20260429-abc123  ▶▷□□□  analyzing r2  ↑13k ↓5k
```

---

## Component Design

### `agentharness/models.py` — additive changes

**`FeatureStatus`** gains one value:

```python
questioning = "questioning"   # product agent answering open questions
```

**`PipelineConfig`** gains two fields:

```python
class PipelineConfig(BaseModel):
    max_revisions: int = 3
    current_revision_round: int = 0
    max_analyst_iterations: int = Field(default=2, ge=0)     # cap; 0 = skip loop
    current_analyst_iteration: int = Field(default=0, ge=0)  # increments on questioning→analyzing
```

**`FeatureState`** gains one immutable-update helper (mirrors `with_status`, `with_event`):

```python
def with_analyst_iteration_incremented(self) -> FeatureState:
    new_config = self.config.model_copy(
        update={"current_analyst_iteration": self.config.current_analyst_iteration + 1}
    )
    return self.model_copy(update={"config": new_config, "updated_at": datetime.now(UTC)})
```

---

### `agentharness/dispatcher.py` — branching logic

#### Removed

```python
_LINEAR_TRANSITIONS["analyzing"]  # replaced by conditional handler
```

#### Added to `STATE_TO_QUEUE`

```python
FeatureStatus.questioning: "product-queue",
```

#### New helper: `_parse_analyst_status`

```python
def _parse_analyst_status(output: str) -> Literal["COMPLETE", "HAS_QUESTIONS"]:
    """Parse the ## Status: line. Safe default: COMPLETE."""
```

- Searches for the pattern `^## Status:\s*(\S+)` (case-sensitive)
- Returns `"HAS_QUESTIONS"` only when captured value is exactly `"HAS_QUESTIONS"`
- All other outcomes (missing line, any other value, malformed) → `"COMPLETE"`
- Mirrors shape of existing `_parse_developer_status`

#### New helper: `_latest_spec_revision`

```python
def _latest_spec_revision(state: FeatureState) -> int:
    return state.config.current_analyst_iteration + 1
```

Used everywhere a `spec` revision number is needed, replacing all hard-coded `1` arguments.

#### New dispatcher: `_dispatch_questioning`

```python
async def _dispatch_questioning(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
```

- Computes `spec_rev = _latest_spec_revision(state)` — this is the spec the analyst just produced
- Builds `TaskMessage`:
  - `task_id = f"{state.feature_id}-questioning-r{spec_rev}"`
  - `input_artifacts = _artifacts_for_phase(state, "questioning")`
  - `output_artifact = phase_artifact_path(feature_id, "answers", spec_rev)`  (e.g. `answers.r1.md`)
  - `agent_role = "product"`
- Sends to `product-queue`
- Returns state transitioned to `questioning` with phase entry and history event

#### New dispatcher: `_dispatch_analyst_rerun`

```python
async def _dispatch_analyst_rerun(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None,
) -> FeatureState:
```

- Increments `current_analyst_iteration` inside the `state_mgr.update(...)` closure (same pattern as `_dispatch_review_result` line 359)
- After increment, `new_rev = state.config.current_analyst_iteration + 1` (the upcoming spec revision)
- Builds `TaskMessage`:
  - `task_id = f"{state.feature_id}-analyzing-r{new_rev}"`
  - `input_artifacts = _artifacts_for_phase(incremented_state, "analyzing")`
  - `output_artifact = phase_artifact_path(feature_id, "spec", new_rev)`
  - `agent_role = "analyst"`
- Sends to `analyst-queue`
- Returns state with `status=analyzing`, incremented counter, phase entry and history event

#### Updated: `dispatch_after_completion`

New branch for `analyzing` (replaces the existing `_LINEAR_TRANSITIONS` lookup):

```python
if status == FeatureStatus.analyzing:
    analyst_status = _parse_analyst_status(agent_output)
    cfg = state.config
    if analyst_status == "COMPLETE" or cfg.current_analyst_iteration >= cfg.max_analyst_iterations:
        if analyst_status == "HAS_QUESTIONS" and cfg.current_analyst_iteration >= cfg.max_analyst_iterations:
            log.warning(
                "max_analyst_iterations cap reached",
                extra={"feature_id": state.feature_id,
                       "current_analyst_iteration": cfg.current_analyst_iteration,
                       "max_analyst_iterations": cfg.max_analyst_iterations},
            )
        return await _dispatch_linear(state, "analyzing", config, queues)
    return await _dispatch_questioning(state, config, queues)

if status == FeatureStatus.questioning:
    return await _dispatch_analyst_rerun(state, config, queues, state_mgr)
```

The existing `_dispatch_linear` for `"analyzing"` continues to transition to `architecting` — no change to that function.

#### Updated: `_artifacts_for_phase`

Signature change from `(feature_id: str, phase: str)` to `(state: FeatureState, phase: str)`:

```python
def _artifacts_for_phase(state: FeatureState, phase: str) -> list[str]:
    feature_id = state.feature_id
    iter_n = state.config.current_analyst_iteration
    spec_rev = _latest_spec_revision(state)   # = iter_n + 1

    if phase == "analyzing":
        # brief + all completed spec revisions + all completed answer revisions
        artifacts = [f"artifacts/{feature_id}/brief.md"]
        artifacts += [phase_artifact_path(feature_id, "spec", i) for i in range(1, spec_rev)]
        artifacts += [phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)]
        return artifacts

    if phase == "questioning":
        # brief + the spec just produced + all prior answers
        artifacts = [f"artifacts/{feature_id}/brief.md"]
        artifacts.append(phase_artifact_path(feature_id, "spec", spec_rev))
        artifacts += [phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)]
        return artifacts

    # Downstream phases consume the latest spec revision
    latest_spec = phase_artifact_path(feature_id, "spec", spec_rev)
    if phase == "architecting":
        return [latest_spec, f"artifacts/{feature_id}/brief.md"]
    if phase == "designing":
        return [latest_spec, phase_artifact_path(feature_id, "arch-review", 1)]
    if phase == "planning":
        return [latest_spec, phase_artifact_path(feature_id, "arch-review", 1),
                phase_artifact_path(feature_id, "design", 1)]
    return []
```

All callers of `_artifacts_for_phase` (`_dispatch_linear`, `build_phase_task`) are updated to pass `state` instead of `feature_id`.

#### Updated: hard-coded `revision=1` call sites

Every `phase_artifact_path(feature_id, "spec", 1)` reference is replaced with `phase_artifact_path(feature_id, "spec", _latest_spec_revision(state))`. Affected locations:

| Location | Old | New |
|---|---|---|
| `_dispatch_fan_out` (line ~187) | `phase_artifact_path(feature_id, "spec", 1)` | `phase_artifact_path(feature_id, "spec", _latest_spec_revision(state))` |
| `build_phase_task` — reviewer inputs (line ~530) | `phase_artifact_path(feature_id, "spec", 1)` | `phase_artifact_path(feature_id, "spec", _latest_spec_revision(state))` |
| `build_phase_task` — phase agents (line ~545) | `output_artifact = phase_artifact_path(feature_id, _output_name(phase), 1)` | revision depends on phase; for `analyzing`/`questioning` use computed revision, for others keep `1` |

`build_phase_task` also needs a `questioning` branch returning the product-agent `TaskMessage` (same shape as the `_dispatch_questioning` task construction).

---

### `agentharness/github_labels.py` — additive constants

```python
FEAT_QUESTIONING = "feat:questioning"
QUEUE_PRODUCT = "queue:product"
```

Extended into all three round-trip dicts:

```python
FEAT_STATUS_LABELS = frozenset({..., FEAT_QUESTIONING})

QUEUE_NAME_TO_LABEL = {..., "product-queue": QUEUE_PRODUCT}

FEATURE_STATUS_TO_LABEL = {..., FeatureStatus.questioning: FEAT_QUESTIONING}
```

`LABEL_TO_FEATURE_STATUS` and `LABEL_TO_QUEUE_NAME` are derived via dict comprehension and require no manual update.

---

### `.agents/product.md` — new agent definition

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

System prompt contract:

- Reads `brief.md`, the latest `spec.r{N}.md` (identified by highest revision number in input artifacts), and all prior `answers.r{M}.md` in ascending revision order
- For each question in `## Open Questions`, outputs:
  ```
  ### Question {n}
  {verbatim question}

  **Answer:** {direct, decisive answer}

  **Rationale:** {1–3 sentences}
  ```
- Outputs only the answered-questions list — no preamble, no summary
- Must not contradict prior `answers.r{M}.md` files
- If a question cannot be definitively answered, must choose the most reasonable default and document the rationale; leaving any question unanswered is forbidden
- Writes output to `answers.md` in the work directory root

---

### `.agents/analyst.md` — prompt addition

Append to the existing system prompt:

```
At the very end of your output, emit exactly one of:
  ## Status: COMPLETE        (when ## Open Questions is empty, absent, or contains only "None.")
  ## Status: HAS_QUESTIONS   (when ## Open Questions has at least one question)

When input artifacts include answers.rN.md files, read them in ascending revision order
(answers.r1.md first). Apply every answer to your revised spec by modifying or removing
the corresponding question and updating any affected sections. Do not reproduce answered
questions as open questions. Produce a single complete, self-contained spec — do not diff.
```

---

### `agentharness/config.py` — one new field

`Config` (the top-level config Pydantic model) gains:

```python
max_analyst_iterations: int = Field(default=2, ge=0)
```

Read from `.pipeline/config.json` top-level key. When `FeatureState` is created, this value is copied into `PipelineConfig.max_analyst_iterations` so each feature carries its own snapshot.

---

### `agentharness/tui.py` — targeted additions

Three changes only:

1. Add `FeatureStatus.questioning` to `_STATUS_ICONS` and `_STATUS_COLORS`
2. Insert `"questioning"` into `_PHASE_ORDER` after `"analyzing"`
3. Extend `TaskPanel.update_tasks` / `_build_task_rows`:
   - Include `questioning` phases in the phase rows loop (already falls out of `_PHASE_ORDER` iteration)
   - In `_build_task_rows`, suffix phase label with ` r{info.revision}` when `info.revision > 1`
4. Extend `TaskPanel.update_tasks` border title to include analyst iteration counter (see UX section above)

---

### `agentharness/tui_state_change.py` and `agentharness/state_change.py`

Search for any exhaustive match over `FeatureStatus` values (e.g. `match status`, `if status == FeatureStatus.X` chains, lookup dicts). Add `questioning` to each. The most likely locations are queue-resolution and display-label mappings.

---

## Data Schemas

### `PipelineConfig` (updated)

```python
class PipelineConfig(BaseModel):
    max_revisions: int = 3
    current_revision_round: int = 0
    max_analyst_iterations: int = Field(default=2, ge=0)
    current_analyst_iteration: int = Field(default=0, ge=0)
```

Serialised into `state.json` (Azure) or issue body JSON (GitHub). Pydantic defaults handle missing fields on old state files — no migration needed.

### `FeatureStatus` enum (updated)

```python
class FeatureStatus(str, Enum):
    brainstorming = "brainstorming"
    brainstormed  = "brainstormed"
    analyzing     = "analyzing"
    questioning   = "questioning"   # NEW
    architecting  = "architecting"
    designing     = "designing"
    planning      = "planning"
    developing    = "developing"
    reviewing     = "reviewing"
    dev_revision  = "dev_revision"
    done          = "done"
    failed        = "failed"
```

### Artifact layout

```
artifacts/{feature_id}/
  brief.md
  spec.r1.md          ← analyst iteration 0  (current_analyst_iteration=0 when produced)
  answers.r1.md       ← product agent, only if HAS_QUESTIONS
  spec.r2.md          ← analyst iteration 1  (current_analyst_iteration=1 when produced)
  answers.r2.md       ← product agent, only if still HAS_QUESTIONS
  spec.r{N}.md        ← final spec handed downstream
  arch-review.r1.md
  design.r1.md
  task-plan.r1.md
  impl/{task}.r1.md
  review/{task}.r1.md
  state.json          ← (Azure only)
```

Invariant: `analyst_output_revision = current_analyst_iteration + 1` at the moment the analyst task runs.

### `TaskMessage` — task ID convention

| Phase | Task ID pattern |
|---|---|
| First analyst run | `{feature_id}-analyzing-r1` |
| Product agent (iteration N) | `{feature_id}-questioning-r{N}` |
| Analyst re-run (revision N+1) | `{feature_id}-analyzing-r{N+1}` |
| Architect, designer, planner | `{feature_id}-{phase}-1` (unchanged) |

Using revision-qualified IDs prevents collision with prior task entries and makes GitHub issue titles unambiguous.

### `.pipeline/config.json` (updated)

```json
{
  "storage_backend": "github",
  "max_analyst_iterations": 2,
  "storage": {
    "connection_string_env": "AZURE_STORAGE_CONNECTION_STRING",
    "container": "pipeline-artifacts"
  },
  "queues": {
    "analyst-queue":   { "agent": ".agents/analyst.md" },
    "product-queue":   { "agent": ".agents/product.md", "visibility_timeout": 300 },
    "architect-queue": { "agent": ".agents/architect.md" },
    "designer-queue":  { "agent": ".agents/designer.md" },
    "planner-queue":   { "agent": ".agents/planner.md" },
    "developer-queue": { "agent": ".agents/developer.md" },
    "review-queue":    { "agent": ".agents/reviewer.md" }
  },
  "defaults": {
    "dead_letter_threshold": 3,
    "max_revisions": 3,
    "poll_interval_seconds": 1.0,
    "github_poll_interval_seconds": 15.0
  }
}
```

### GitHub label additions

| Constant | Label string | Purpose |
|---|---|---|
| `FEAT_QUESTIONING` | `feat:questioning` | Feature-level status label |
| `QUEUE_PRODUCT` | `queue:product` | Task routing to product agent |

Both are registered in `FEAT_STATUS_LABELS`, `QUEUE_NAME_TO_LABEL`, and `FEATURE_STATUS_TO_LABEL` for full round-trip serialisation.

### Structured log payload — cap-reached event

```python
log.warning(
    "max_analyst_iterations cap reached — proceeding to architecting",
    extra={
        "feature_id": state.feature_id,
        "current_analyst_iteration": cfg.current_analyst_iteration,
        "max_analyst_iterations": cfg.max_analyst_iterations,
    },
)
```

Grep key: `"max_analyst_iterations cap reached"`.
```