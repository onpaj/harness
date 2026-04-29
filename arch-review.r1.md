```markdown
# Architecture Review: Product Agent — Analyst Open Questions Loop

## Architectural Fit Assessment

The feature is a clean structural extension of the existing pipeline rather than a redesign. It reuses every architectural primitive already in place: agent-as-markdown definition, queue-per-phase routing, immutable `FeatureState` updates under a state lease, single-output artifact uploads with `output_file_glob`, and the `dispatch_after_completion` state-machine hub. No new subsystems are required.

The integration cuts only three surfaces:

1. **Dispatcher** — the existing `_LINEAR_TRANSITIONS["analyzing"]` entry must be replaced by a conditional handler. The shape mirrors what `_dispatch_serial_next` already does (parse a status code from output, branch).
2. **Models** — additive enum value (`FeatureStatus.questioning`) and two additive fields on the existing `PipelineConfig` Pydantic model (the spec calls it `FeatureStateConfig`; the codebase actually uses `PipelineConfig` — see Specification Amendments below).
3. **Artifact revision plumbing** — the analyst's output revision is no longer always `1`. This is the single non-trivial change: `phase_artifact_path(..., "spec", revision)` is hard-coded to `revision=1` in three places (`_dispatch_linear`, `_dispatch_fan_out`, `_artifacts_for_phase`, `build_phase_task`). Downstream agents must consume the *highest existing* spec revision.

The bounded loop with conditional Opus dispatch fits the project's existing cost-control discipline (per-task review caps, `max_revisions`, dead-letter thresholds). The default `max_analyst_iterations = 2` matches the conservative posture of the rest of the codebase.

The only meaningful tension: `_artifacts_for_phase(feature_id, phase)` currently takes a phase string with no state context. Computing the accumulated artifact list for `analyzing` re-runs requires either passing `state` (or `current_analyst_iteration`) into this helper, or enumerating revisions from the artifact store. Passing state is simpler and consistent with `build_phase_task`.

## Proposed Architecture

### Component Overview

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          dispatch_after_completion                         │
│                                                                            │
│   completed_phase = analyzing                                              │
│         │                                                                  │
│         ▼                                                                  │
│   _parse_analyst_status(output)  ──► COMPLETE? ──► _dispatch_linear        │
│         │                                          (architecting)          │
│         │ HAS_QUESTIONS                                                    │
│         ▼                                                                  │
│   iter < max?  ── no ─►  log warning + _dispatch_linear(architecting)      │
│         │ yes                                                              │
│         ▼                                                                  │
│   _dispatch_questioning(state, config, queues)                             │
│       enqueue product → spec.r{N}, answers.r{N} expected                   │
│                                                                            │
│   completed_phase = questioning                                            │
│         │                                                                  │
│         ▼                                                                  │
│   _dispatch_analyst_rerun(state, config, queues)                           │
│       config.current_analyst_iteration += 1 (in updater closure)           │
│       enqueue analyst with [brief, spec.r1..rN, answers.r1..rN]            │
│       output target: spec.r{N+1}                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

```
.agents/product.md  ──── new agent definition (Opus, no tools, output_file_glob: answers.md)
.pipeline/config.json
   queues.product-queue → .agents/product.md
   max_analyst_iterations: 2
agentharness/github_labels.py
   FEAT_QUESTIONING + QUEUE_PRODUCT (additive, round-trip mappings)
agentharness/models.py
   FeatureStatus.questioning
   PipelineConfig.max_analyst_iterations / current_analyst_iteration
agentharness/dispatcher.py
   STATE_TO_QUEUE[questioning] = "product-queue"
   remove _LINEAR_TRANSITIONS["analyzing"]
   _parse_analyst_status, _dispatch_questioning, _dispatch_analyst_rerun
   _artifacts_for_phase(state, phase) — signature change
   _output_revision(phase, state) — new helper for revision number
agentharness/run_task.py
   no changes (output_file_glob plumbing already supports glob → blob path)
```

### Key Design Decisions

#### Decision 1: Where the iteration counter lives

**Options considered:**
1. New top-level field on `FeatureState` (e.g. `analyst_iteration: int = 0`).
2. Add to existing `PipelineConfig` (the runtime config nested inside `FeatureState.config`).
3. Derive from `state.history` events.

**Chosen approach:** Option 2 — add `max_analyst_iterations` and `current_analyst_iteration` to `PipelineConfig`.

**Rationale:** `PipelineConfig` is already the home of `max_revisions` / `current_revision_round`, which are exactly the same shape (cap + counter). Reusing it keeps related concepts colocated and makes the immutable update pattern in `_dispatch_review_result` (line 359-361 in `dispatcher.py`) directly transferable. Deriving from history (option 3) is fragile — history is an append-only log meant for human inspection, not authoritative state. A new top-level field (option 1) splits semantically identical knobs across two locations.

#### Decision 2: Spec revision numbering scheme

**Options considered:**
1. Hard-code `spec.r1.md` everywhere; overwrite on re-run (lose history).
2. Use `current_analyst_iteration + 1` as the spec revision.
3. Track `analyst_revision: int` separately on state.

**Chosen approach:** Option 2 — `spec.r{current_analyst_iteration + 1}.md`. The product agent's output is `answers.r{current_analyst_iteration + 1}.md` (matching the spec it answered).

**Rationale:** The counter increments on `questioning → analyzing`, so:
- Initial state: `current_analyst_iteration = 0` → first analyst run produces `spec.r1.md`.
- After product agent runs and counter increments to `1` → next analyst run produces `spec.r2.md`.
- If product re-runs (cap permitting), counter increments to `2` → `spec.r3.md`.

This is invariant: **`analyst_output_revision = current_analyst_iteration + 1`** at the moment the analyst runs. No separate field, no possibility of drift. Re-running an analyst task under `_recover_task` produces the same revision (idempotent). Overwriting (option 1) destroys forensic value and breaks the artifact-history contract used by NFR-5.

#### Decision 3: Downstream consumption of the "current spec"

**Options considered:**
1. Always pass the highest-numbered `spec.r{N}.md` to architect/designer/planner/developer.
2. Copy the final spec to `spec.md` (no revision suffix) when handing off.
3. Pass *all* spec revisions to downstream agents.

**Chosen approach:** Option 1. The dispatcher computes `latest_spec_revision = state.config.current_analyst_iteration + 1` (or `1` if the loop never ran) and rewrites `_artifacts_for_phase` for `architecting`/`designing`/`planning` and `_dispatch_fan_out` to use that revision number for `phase_artifact_path(feature_id, "spec", revision)`.

**Rationale:** Option 2 doubles writes and creates a synchronization point. Option 3 bloats prompts unnecessarily — by definition, the latest spec is authoritative, having absorbed all answers. Option 1 is a tiny read-time computation that follows the existing single-revision pattern.

#### Decision 4: How the product agent's output filename is computed

**Options considered:**
1. Hard-code `output_artifact = artifacts/{feature_id}/answers.r{N}.md` in the dispatcher when enqueueing.
2. Have the agent itself produce a revision-suffixed filename.
3. Map `output_file_glob: answers.md` → revision-suffixed blob via `_resolve_output_file`.

**Chosen approach:** Option 1. The dispatcher already controls `task.output_artifact` (e.g. `_dispatch_linear` at `dispatcher.py:150`). It computes `answers.r{N}.md` directly when building the questioning task. The agent's `output_file_glob: answers.md` is only used inside `_resolve_output_file` to pick which file in the work_dir to upload; the upload destination is `task.output_artifact`, which the dispatcher sets.

**Rationale:** The existing `output_file_glob` pattern (see `run_task.py:111-113` and `_resolve_output_file`) decouples local filename from blob path. The agent writes `answers.md` to its work_dir; the dispatcher chose to store it at `answers.r{N}.md`. No agent-side change needed; no new plumbing.

#### Decision 5: Atomicity of the iteration counter increment

**Options considered:**
1. Read state, mutate counter, write — outside the lease.
2. Increment inside the `state_manager.update()` closure (held under blob lease / GitHub optimistic write).
3. Track via history events and recompute.

**Chosen approach:** Option 2. The increment must happen as part of the same `with_status(analyzing)` transition update. Pattern: a new `FeatureState.with_analyst_iteration_incremented()` helper used inside the updater lambda passed to `state_mgr.update()`.

**Rationale:** This mirrors `_dispatch_review_result`'s `current_revision_round` increment (line 359). It guarantees exactly-once semantics under observer crash + replay. A separate update would create a window where status=analyzing but counter not yet incremented — observable race.

#### Decision 6: Default analyst status when the line is missing

**Options considered:**
1. Default to `COMPLETE` (proceed) — fail-open.
2. Default to `HAS_QUESTIONS` (loop) — fail-closed.
3. Treat as parse error; mark feature failed.

**Chosen approach:** Option 1 (per spec FR-1). 

**Rationale:** The codebase precedent is `_parse_developer_status` (line 378-381) which defaults to `DONE`. Fail-open is consistent with existing behavior and protects in-flight features during deployment (NFR-3). Fail-closed would risk unbounded Opus spend on legacy specs that lack the new contract.

## Implementation Guidance

### Directory / Module Structure

**New files:**
- `.agents/product.md` — agent definition (frontmatter + system prompt)

**Modified files:**
- `agentharness/models.py` — add `FeatureStatus.questioning`; add two fields to `PipelineConfig`; add `FeatureState.with_analyst_iteration_incremented()`.
- `agentharness/dispatcher.py` — remove `_LINEAR_TRANSITIONS["analyzing"]`; add `_parse_analyst_status`, `_dispatch_questioning`, `_dispatch_analyst_rerun`; update `_artifacts_for_phase` signature to `(state, phase)` and rewrite mapping; update `_dispatch_fan_out` and `build_phase_task` to use `latest_spec_revision`; add `STATE_TO_QUEUE[questioning]`.
- `agentharness/github_labels.py` — add `FEAT_QUESTIONING = "feat:questioning"`, `QUEUE_PRODUCT = "queue:product"`; extend `FEAT_STATUS_LABELS`, `QUEUE_NAME_TO_LABEL`, `FEATURE_STATUS_TO_LABEL` round-trip dicts.
- `.pipeline/config.json` — add `product-queue` queue entry and top-level `max_analyst_iterations: 2`.
- `agentharness/.agents/analyst.md` — append the `## Status:` contract and the multi-`answers.rM.md` reading instruction.
- `agentharness/tui.py` — add `questioning` to status filter / phase rendering; surface `current_analyst_iteration / max_analyst_iterations` in feature detail.
- `agentharness/state_change.py`, `agentharness/tui_state_change.py` — extend any `FeatureStatus` switch tables (search for usages).
- `tests/test_dispatcher.py` — new tests per FR-7 acceptance.

**No changes:**
- `run_task.py`, `prompt_builder.py`, `agent_runner.py`, `storage.py`, queue/artifact backend modules. The new agent rides on existing primitives.

### Interfaces and Contracts

**Models (additive):**

```python
class FeatureStatus(str, Enum):
    # ... existing values ...
    questioning = "questioning"   # NEW

class PipelineConfig(BaseModel):
    max_revisions: int = 3
    current_revision_round: int = 0
    max_analyst_iterations: int = Field(default=2, ge=0)        # NEW
    current_analyst_iteration: int = Field(default=0, ge=0)     # NEW

class FeatureState(BaseModel):
    # ... existing methods ...
    def with_analyst_iteration_incremented(self) -> FeatureState:
        new_config = self.config.model_copy(
            update={"current_analyst_iteration": self.config.current_analyst_iteration + 1}
        )
        return self.model_copy(update={"config": new_config, "updated_at": datetime.now(UTC)})
```

**Dispatcher contract:**

```python
def _parse_analyst_status(output: str) -> Literal["COMPLETE", "HAS_QUESTIONS"]:
    """Mirror of _parse_developer_status. Default: COMPLETE."""

def _latest_spec_revision(state: FeatureState) -> int:
    """Return state.config.current_analyst_iteration + 1.
    The current analyst run produces spec.r{N+1}.md, where N is the iteration
    counter at the moment the analyst was last enqueued."""

async def _dispatch_questioning(state, config, queues) -> FeatureState: ...
async def _dispatch_analyst_rerun(state, config, queues, state_mgr) -> FeatureState:
    """Increments current_analyst_iteration inside the next state_mgr.update call.
    Returns FeatureState with status=analyzing and the new task enqueued."""

def _artifacts_for_phase(state: FeatureState, phase: str) -> list[str]:
    """Signature change: takes state instead of feature_id.
    For 'analyzing': returns brief.md + spec.r1..rN + answers.r1..rN
                     where N = current_analyst_iteration (only revisions that have
                     completed are listed; the new output revision is excluded).
    For 'questioning': returns brief.md + spec.r{N+1}.md + answers.r1..rN
                       where N+1 is the spec just produced.
    For other phases: unchanged but uses _latest_spec_revision(state)."""
```

**Agent definition (`.agents/product.md`):**

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

**Pipeline config (`.pipeline/config.json`):**

```json
{
  "max_analyst_iterations": 2,
  "queues": {
    "analyst-queue":   { "agent": ".agents/analyst.md" },
    "product-queue":   { "agent": ".agents/product.md" },
    "architect-queue": { "agent": ".agents/architect.md" },
    "...": "..."
  }
}
```

`Config` Pydantic model (`config.py`) gains a top-level `max_analyst_iterations: int = 2` field. `FeatureState.create(...)` (or wherever new features are seeded) reads `config.max_analyst_iterations` into `PipelineConfig.max_analyst_iterations` so each feature carries its own snapshot.

**Task ID convention:** Analyst re-runs use `task_id = f"{feature_id}-analyzing-r{N+1}"` (where `N+1` is the new revision) instead of `-1` to avoid collisions with prior iterations. Product agent uses `task_id = f"{feature_id}-questioning-r{N}"`.

### Data Flow

**Path A — Brief is complete (no Opus, baseline cost):**

```
brainstormed → analyzing  (analyst writes spec.r1, "## Status: COMPLETE")
            → architecting (unchanged downstream)
            → ... → done
```

**Path B — One round of clarification:**

```
brainstormed → analyzing                    # iter=0, output=spec.r1
            ↓ HAS_QUESTIONS, iter (0) < max (2)
            → questioning                   # input=[brief, spec.r1], output=answers.r1
            ↓ completed
            → analyzing                     # iter incremented to 1, output=spec.r2
                                           # input=[brief, spec.r1, spec.r2-target?, answers.r1]
                                           # NOTE: only existing artifacts pre-run are passed
            ↓ "## Status: COMPLETE"
            → architecting                  # consumes spec.r2 (latest)
            → ...
```

**Path C — Cap reached:**

```
... → analyzing (iter=2, output=spec.r3)
    ↓ HAS_QUESTIONS, iter (2) >= max (2)
    log.warning("max_analyst_iterations cap reached", feature_id=…, current=2, max=2)
    → architecting                        # consumes spec.r3 with open questions intact
```

**Path D — Cap = 0 (kill switch):**

`max_analyst_iterations: 0` → first `HAS_QUESTIONS` instantly takes Path C. Product agent is never invoked.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Hard-coded `revision=1` in `phase_artifact_path(..., "spec", 1)` calls causes downstream agents to read the *first* spec instead of the latest after a loop. | **HIGH** | Audit every `phase_artifact_path(..., "spec", 1)` call site (`_dispatch_linear:150`, `_dispatch_fan_out:188`, `_artifacts_for_phase:420-432`, `_enqueue_per_task_review:260`, `_dispatch_review_result:336`, `build_phase_task:530-532`). Replace with `_latest_spec_revision(state)`. Add a regression test that puts spec.r2 in storage and verifies architect input list. |
| `_artifacts_for_phase` signature change breaks callers. | MEDIUM | Audit callers (only `_dispatch_linear`, `build_phase_task`) and update both in the same change set. Type-checker (mypy) catches misses. |
| Counter increment outside the lease produces double-increment under observer-crash replay. | MEDIUM | Increment exclusively inside the `state_mgr.update(...)` closure used in `_dispatch_analyst_rerun`. Test by injecting a mid-update exception and verifying single increment. |
| Analyst gets confused by accumulated artifact context (multiple specs + answers) and produces a malformed spec. | MEDIUM | Update analyst system prompt to explicitly state read order ("apply `answers.r1.md` first, then `answers.r2.md`, …; produce a single fresh spec — do not diff"). |
| GitHub backend missing `feat:questioning` / `queue:product` labels in repository → tasks silently never get claimed. | MEDIUM | The GitHub backend creates labels on demand (verify via `github_state.py` / `github_queue.py`); if not, add a one-time label provisioning step to `agentharness init`. Document in CLAUDE.md and `/azure-storage` skill (Azure provisioning still required). |
| Product agent answers contradict prior `answers.r{M}.md`, causing analyst oscillation. | LOW | Product system prompt explicitly forbids contradiction with prior answer files (already in spec FR-3). Bounded loop guarantees termination regardless. |
| `output_file_glob: answers.md` matches files in subdirectories of `work_dir` (per `_resolve_output_file` glob). | LOW | Agent system prompt instructs writing to `answers.md` at work_dir root. Existing analyst already follows the same pattern (`spec.md`). |
| TUI rendering breaks on the new enum value via an exhaustive match. | LOW | Search for `FeatureStatus.` switch tables (`tui_state_change.py`, `state_change.py`, `tui.py`) and add `questioning` branches. |
| Stale state files from features created before the change: missing `current_analyst_iteration` / `max_analyst_iterations`. | LOW | Pydantic field defaults (`= 0`, `= 2`) handle deserialization seamlessly (NFR-3 already specified). |
| Concurrent observers re-running a `questioning` task produce duplicate `answers.r{N}.md`. | LOW | Idempotent: same `task_id`, same `output_artifact`, same revision. The blob upload overwrites with identical content. The `_recover_task` retry path uses the same TaskMessage. |

## Specification Amendments

1. **Pydantic class name correction.** Spec FR-5 calls the model `FeatureStateConfig`, but the actual class is `agentharness.models.PipelineConfig` (instantiated as `FeatureState.config`). All field additions land on `PipelineConfig`. Update spec to match.

2. **`_artifacts_for_phase` signature.** Spec implies the helper still takes `(feature_id, phase)`. Real implementation needs `state` to know `current_analyst_iteration`. Change signature to `(state: FeatureState, phase: str)`. Update both call sites in dispatcher.

3. **Latest-spec consumption is not free.** Spec asserts "Downstream agents (architect, designer, planner) receive the highest-revision `spec.r{N}.md`" but does not list the call sites that hard-code `revision=1`. Add an explicit acceptance criterion: *"every `phase_artifact_path(..., 'spec', 1)` reference in `dispatcher.py` is replaced with a `_latest_spec_revision(state)` call."* The reviewer/dev review path also references `spec.r1` (line 260, 336) — these must follow the same rule.

4. **Task ID disambiguation for re-runs.** Spec does not specify task IDs. Use `f"{feature_id}-analyzing-r{N}"` and `f"{feature_id}-questioning-r{N}"` to avoid the per-task orphan check (`run_task.py:60`) and to make logs / GitHub issue titles unambiguous.

5. **GitHub label provisioning.** Spec FR-6 says "for the GitHub backend, no manual setup needed" — confirm whether the backend auto-creates `feat:questioning` and `queue:product` on first issue with that label. If not (verify via `github_state.py` / `github_queue.py`), add a step to `agentharness init` or document the label-creation requirement.

6. **Product agent system prompt: ordering rule.** The spec mentions reading prior answers but should explicitly require ascending-revision order: *"read `answers.r1.md`, `answers.r2.md`, … in ascending revision order; later answers do not contradict earlier ones, but if they appear to, treat the later answer as authoritative and document the change."*

7. **Worktree behavior for re-runs.** The analyst is currently a `allowed_tools: []` agent — no work_dir mutations are committed. Confirm and document: re-runs do not create commits; only the spec.r{N+1}.md artifact is uploaded. No worktree churn expected.

8. **Cap=0 semantics.** Add an explicit acceptance test: with `max_analyst_iterations: 0` set in config, a `HAS_QUESTIONS` analyst output must dispatch directly to architecting without enqueueing the product agent. The check is `current_analyst_iteration < max_analyst_iterations`, which is `0 < 0 = False` — already correct, but worth pinning down with a test.

## Prerequisites

1. **Anthropic Opus access** for `claude-opus-4-7` (already required by analyst — no new credentials).
2. **Azure backend only** — provision `product-queue` via `/azure-storage` skill before deploying this change. Required ahead of time; new queue creation is not yet automated for Azure.
3. **GitHub backend** — verify (or add) automatic creation of new labels `feat:questioning` and `queue:product`. Confirm by inspection of `github_state.py` / `github_queue.py` label-handling code; if labels are not auto-created, add a manual provisioning step to the deployment runbook and to `agentharness init`.
4. **`.pipeline/config.json` migration** — existing deployments must add `product-queue` and (optionally) `max_analyst_iterations: 2` before the new code runs. The default falls back to `2` if absent, so this is a soft prerequisite for tunability rather than correctness.
5. **In-flight features** — features mid-pipeline at the moment of deploy will have no `current_analyst_iteration` field in their persisted state; Pydantic default (`0`) backfills on load. No data migration needed (NFR-3).
6. **Dispatcher tests must be updated in lockstep.** The existing happy-path test for `analyzing → architecting` will continue to pass only if the analyst output snapshot is updated to include `## Status: COMPLETE`. Coordinate the agent-prompt update and the test-fixture update in the same change set.
```