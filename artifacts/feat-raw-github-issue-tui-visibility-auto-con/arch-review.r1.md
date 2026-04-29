```markdown
# Architecture Review: Raw GitHub Issue TUI Visibility + Auto-Conversion

## Architectural Fit Assessment

This feature is a **clean, surgical extension** of the existing GitHub backend. It aligns well with established patterns:

- **No new abstractions, no new components, no new dependencies.** It extends three existing modules (`github_state.py`, `brainstorm.py`, `tui.py`) and reuses every existing helper (`_replace_state_block`, `_state_from_issue`, `GitHubClient`, `GitHubArtifactStore`, `create_state_manager`).
- **Backend isolation is preserved.** All changes are inside the GitHub backend's slice; the Azure path and the `StateBackend` protocol are untouched. The new `patch_existing_issue` is a GitHub-specific method (not part of the protocol) — a deliberate restriction matching `feat:brainstormed`-style label semantics that have no Azure equivalent.
- **The state lifecycle gains one new boundary** — "raw" vs "initialized" — but no new state-machine vertex. The synthetic `FeatureState` lives entirely in memory; the on-disk shape (issue body + labels) is unchanged for raw issues until conversion.

Main integration points: `GitHubStateManager.list_features` (read path), `enqueue_planner` (write path/state-machine entry), and `tui.action_open_state_change` (UI guard). The existing `_phase_bar`/`_task_summary` already handle empty inputs, so TUI rendering needs no changes.

The one subtle architectural question — "is `len(state.history) == 0` a meaningful discriminator, or are we overloading a data field?" — is answered by the spec adopting it as the canonical signal. This is the right call (zero model churn) but warrants a named helper to keep call sites readable.

## Proposed Architecture

### Component Overview

```
                          ┌─────────────────────────────────────────┐
                          │ GitHub Issue (label: agent)             │
                          │   body: <free text> [+ optional state]  │
                          └────────────────┬────────────────────────┘
                                           │
                                           │ GitHubClient.list_issues
                                           ▼
        ┌────────────────────────────────────────────────────────┐
        │ GitHubStateManager.list_features()                     │
        │                                                        │
        │  parse body for agentharness-state block               │
        │     ├── present  → _state_from_issue() (existing)      │
        │     └── absent   → _synthesize_raw_state() (NEW)       │
        │                                                        │
        │  dedup: newest issue wins per feature_id               │
        └────────────────────────┬───────────────────────────────┘
                                 │ list[FeatureState]
                                 ▼
                ┌────────────────┴────────────────┐
                ▼                                 ▼
      ┌───────────────────┐            ┌──────────────────────┐
      │ TUI: render rows  │            │ enqueue_planner(fid) │
      │  is_raw → guard   │            │   try: get(fid)      │
      │   action_change   │            │   except KeyError:   │
      └───────────────────┘            │     _convert_raw_    │
                                       │      issue()  (NEW)  │
                                       │   ↓                  │
                                       │   patch_existing_    │
                                       │     issue()   (NEW)  │
                                       │   ↓                  │
                                       │   queue analyst task │
                                       └──────────────────────┘
```

### Key Design Decisions

#### Decision 1: "Raw" state is implicit, not modeled

**Options considered:**
- (A) Add `is_raw: bool` field to `FeatureState`.
- (B) Add a 13th `FeatureStatus.raw` enum value.
- (C) Use `len(state.history) == 0` as the discriminator (spec choice).

**Chosen approach:** (C), with a new computed property `FeatureState.is_raw -> bool` exposing `not self.history` so call sites read declaratively rather than poking at internals.

**Rationale:** (A) requires a model migration and risks divergence between persisted state and the field's value (the field is meaningless for already-stored features). (B) would multiply state-machine transitions and force every dispatcher branch to think about it. (C) costs zero migration: the absence of a `brief_uploaded` history event is already the natural signal and is true by construction for any synthesized state. The `is_raw` property pays one line of code for readable guards (`if state.is_raw: ...`) instead of `len(state.history) == 0` scattered across the code.

#### Decision 2: Slug algorithm becomes a single shared helper

**Options considered:**
- (A) Re-implement the slug algorithm inside `_convert_raw_issue` and `list_features`, accepting drift risk with `convertforagent`.
- (B) Extract to a shared helper used everywhere a feature_id is derived from a title (or H1 heading).

**Chosen approach:** (B). Add `agentharness/slug.py` (single function) — or, equivalently, a top-level `slug_title(title: str) -> str` in `github_state.py`. Both `brainstorm._slug_from_brief` (which currently slugs the H1 line of the brief) and the new raw-issue path call into it. The skill `/convertforagent` is left as-is (it's a Bash/Python one-shot and out of scope), but the in-code path is unified.

**Rationale:** The spec explicitly requires `feature_id` to match what `/convertforagent` would produce. There are currently two slug implementations (the bash skill + `_slug_from_brief`). Keeping a third in `_convert_raw_issue` is a guaranteed source of "why doesn't my issue match" bugs. One algorithm, one place.

#### Decision 3: `get()` semantics for raw issues stay unchanged (raises `KeyError`)

**Options considered:**
- (A) `get(feature_id)` also returns a synthetic state for raw issues (consistent with `list_features`).
- (B) `get(feature_id)` keeps raising `KeyError` for raw issues (i.e., when no state JSON block is present).

**Chosen approach:** (B). `enqueue_planner` already relies on `KeyError` to detect "needs conversion." Making `get()` synthesize would force a second discriminator (`is_raw`) and break the existing contract that `get()` returns a "real" persisted state suitable for `update()`.

**Rationale:** `list_features` is a discovery operation (best-effort, render-friendly). `get()` is a precondition for `update()`, which would corrupt a synthetic state by writing it back. Asymmetry is intentional and worth a one-line docstring.

#### Decision 4: `patch_existing_issue` is not part of the `StateBackend` protocol

**Chosen approach:** Add it as a public method on `GitHubStateManager` only, not on `StateBackend`.

**Rationale:** The Azure backend has no equivalent (no in-place issue concept). Forcing the protocol to grow a method one implementation can't satisfy is a leak. `_convert_raw_issue` lives in `brainstorm.py` and knows `config.storage_backend == "github"`; the cast to `GitHubStateManager` is locally scoped.

## Implementation Guidance

### Directory / Module Structure

```
agentharness/
  github_state.py          ← extend list_features; add patch_existing_issue;
                             add _synthesize_raw_state helper; expose slug_title
  brainstorm.py            ← add _convert_raw_issue; add GitHub pre-flight
                             to enqueue_planner; refactor _slug_from_brief to
                             call shared slug helper
  models.py                ← add FeatureState.is_raw computed property
  tui.py                   ← guard in action_open_state_change

tests/
  test_github_state.py     ← list_features synthetic-state cases;
                             patch_existing_issue cases (idempotency,
                             label add, body replacement)
  test_brainstorm.py       ← _convert_raw_issue happy path; KeyError on
                             missing issue; pre-flight in enqueue_planner;
                             Azure path unchanged
  test_tui.py              ← action_open_state_change guard for raw features
                             (only if existing tui tests exist; otherwise skip)
```

No new files except optionally `agentharness/slug.py` (single function); placing `slug_title` directly in `github_state.py` is also acceptable since that is the only non-brainstorm consumer.

### Interfaces and Contracts

**`agentharness/models.py` — `FeatureState`**
```python
@property
def is_raw(self) -> bool:
    """A feature is 'raw' when discovered from a labeled issue with no state block."""
    return not self.history
```

**`agentharness/github_state.py`**
```python
def slug_title(title: str) -> str:
    """Return a 40-char slug — must match /convertforagent's algorithm."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40]


def _synthesize_raw_state(issue: dict) -> FeatureState:
    """Build a synthetic FeatureState for a labeled issue without a state block."""
    # uses slug_title(issue["title"]); status=brainstormed; history=[]; ...


class GitHubStateManager:
    async def patch_existing_issue(
        self,
        issue_number: int,
        state: FeatureState,
        brief_content: str = "",
    ) -> None:
        """Embed harness state into an existing issue (does not create one)."""
```

**Contract for `list_features`:**
- For each issue with `feature_marker`: try `_state_from_issue` → on parse failure or missing block, fall back to `_synthesize_raw_state`. Never raise.
- Drop the existing "skipped issue: no state block" `log.warning` (it would now fire on every refresh and be noise). Replace with `log.debug` if anything is logged at all.
- Dedup rule (newest issue per `feature_id`) applies to mixed raw + initialized — implementation already reduces to a single issue dict before parsing, so no change needed beyond moving the synthesis into the per-issue parse step.

**Contract for `patch_existing_issue`:**
- `ensure_labels([feature_marker, feat:brainstormed])` is idempotent — reuse the existing helper.
- The body construction must re-use `_replace_state_block` (handles both append and replace cases).
- If `brief_content` is non-empty AND the existing body does not contain it, prepend brief to body before applying `_replace_state_block`. Otherwise leave body untouched and only update the state block. This matches the existing `convertforagent` behavior of "body untouched except the trailing block."
- Idempotent: calling twice with the same `state` produces byte-identical bodies (modulo timestamps inside the state JSON).

**Contract for `_convert_raw_issue`:**
- Order of side effects: **branch → artifact upload → patch issue**. The issue patch is the commit point; if it fails, the branch and artifact are leftover but cause no inconsistency on retry (branch reuse is no-op; artifact PUT is idempotent given branch SHA).
- On `feature_id` match: compare `slug_title(issue["title"]) == feature_id_minus_prefix`. Use the same helper used during synthesis to guarantee round-trip equality.

**Contract for `enqueue_planner` pre-flight:**
- Guard is exactly `if config.storage_backend == "github": try get() except KeyError: convert`. Do NOT also call `state_mgr.list_features()` here — adding a list call doubles the GitHub API cost on the hot path.
- Pre-flight runs **before** the existing `state_mgr.update(...)` call so that the update operates on the freshly initialized state.

### Data Flow

**Render flow (TUI refresh, every 2s):**
```
TUI tick → list_features()
            → GitHub.list_issues(label=feature_marker)
            → for each issue: parse body
                · state block present  → _state_from_issue (existing)
                · state block absent   → _synthesize_raw_state (new)
            → dedup (newest wins) → list[FeatureState]
TUI render: each row → _phase_bar/_task_summary handle empty inputs → ◎ □□□□□ brainstormed
```

**Conversion flow (i pressed in TUI, or `agentharness implement`):**
```
enqueue_planner(fid, config)
  ├─ if backend == "github":
  │     try state_mgr.get(fid)
  │     except KeyError:
  │        _convert_raw_issue(fid, config)
  │           1. list_issues(label=feature_marker)
  │           2. find by slug_title(title) match  (raises ValueError if none)
  │           3. create_ref(refs/heads/<fid>, sha=default_branch.sha)  [skip on 422]
  │           4. GitHubArtifactStore.upload(brief.md, body)
  │           5. patch_existing_issue(issue_number, state, brief_content)
  │
  ├─ state_mgr.update(fid, status=analyzing, event="pipeline_started")  [unchanged]
  ├─ ...checkout, write brief.md to worktree...                        [unchanged]
  └─ queue.send_task(analyst task)                                     [unchanged]
```

**State-change guard (TUI):**
```
user presses S
  → action_open_state_change()
    → state.is_raw?  yes → notify("Convert to harness feature first (press i)") + return
                     no  → push_screen(StateChangeModal)  (existing)
```

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Slug divergence between `_convert_raw_issue` matcher and `list_features` synthesizer | HIGH | Single shared `slug_title` helper used by both. Add a unit test asserting `slug_title("My Feature!") == "my-feature"`. |
| Slug divergence with `/convertforagent` skill | MEDIUM | Document the algorithm contract in a comment above `slug_title`; add a unit test with the exact regex/length the skill uses. The skill itself is out of scope but should be migrated to call the harness in a follow-up. |
| `get(feature_id)` returns synthetic state for raw issues, breaking `update()` | HIGH | Decision 3 above — keep `get()` raising `KeyError`. Add a unit test asserting `get("feat-raw")` raises. |
| Empty `history` discriminator misclassifies a real but freshly-initialized feature whose history was somehow cleared | LOW | Real features always start with `history=[brief_uploaded]` event (see `upload_brief` in `brainstorm.py`). A feature with empty history that has a state block in the body would still parse via `_state_from_issue` and be classified as initialized via the parse path, never via synthesis. The `is_raw` property is only meaningful for states produced by `list_features` or computed locally; never trust it after `get()`. |
| `_convert_raw_issue` partial failure leaves orphan branch/artifact on retry | LOW | Operation is idempotent: branch creation is 422-tolerant; artifact upload uses existing PUT-with-SHA pattern; issue patch replaces the state block. Document idempotency in the function docstring. |
| TUI refresh log spam from removing the "no state block" warning | LOW | Drop the warning entirely (or downgrade to `log.debug`). Synthesis is the new normal — it deserves no log line per refresh. |
| `enqueue_planner` race: two callers convert the same issue concurrently | LOW | GitHub PATCH on issue body is atomic; the second writer overwrites the same state block. `patch_existing_issue` is idempotent so the result is consistent. Branch creation 422 is tolerated. No lock needed. |
| `feature_marker` is configurable; tests must not hard-code `"agent"` | LOW | Tests use `feature_marker="agent"` via fixture, mirroring existing pattern in `test_github_state.py`. |
| TUI guard uses `state.history` directly while contract is `is_raw` | LOW | Add `is_raw` property as part of this change so all guards (TUI + future code) call it consistently. |

## Specification Amendments

1. **Add `FeatureState.is_raw` as a computed property.** The spec describes the discriminator as "test `len(state.history) == 0`"; promoting that to a property documents intent and prevents drift. Use `state.is_raw` everywhere the spec calls for the empty-history check (FR-5, future code).

2. **Extract `slug_title` to a shared helper.** The spec's "Open Questions" hints at this without committing. Make it a hard requirement: one implementation, used by both `_convert_raw_issue` (matching) and `_synthesize_raw_state` (generation), so a round-trip `synthesize → match` is guaranteed equal. Place it in `agentharness/github_state.py` (top-level function).

3. **Refactor `brainstorm._slug_from_brief` to delegate to `slug_title`.** Currently it strips the H1 prefix then slugs; after refactor, the slug step calls `slug_title`. This keeps a single algorithm under test.

4. **Drop the per-refresh `log.warning` in `list_features`** — synthesis replaces it. The spec leaves this as "operator preference"; default to silence.

5. **Clarify `get()` semantics in a docstring.** Add: "Raises `KeyError` for issues without an embedded state block (raw issues), even when `list_features()` would surface them as synthetic states. Convert via `_convert_raw_issue` before calling `update()`."

6. **`_convert_raw_issue` accepts an optional `state_mgr` parameter** (or constructs one internally). Recommend constructing internally and closing in a `try/finally` to mirror `upload_brief`'s resource management. The spec is silent on this; making it explicit prevents leaked HTTP clients on errors.

## Prerequisites

None of the following block implementation, but each must be in place before the change behaves correctly:

- **`feature_marker` label exists in repo.** Already an existing requirement; `convertforagent` and `create()` both use `ensure_labels`. `_convert_raw_issue` and `patch_existing_issue` will likewise call `ensure_labels`, so no manual setup needed.
- **`feat:brainstormed` label exists in repo.** Created on demand by `patch_existing_issue` via `ensure_labels` — no manual setup.
- **`GITHUB_TOKEN` with `repo` scope.** Existing requirement; no change.
- **Default branch SHA reachable.** `GitHubClient.get_default_branch()` already exists; no infra change.
- **Tests baseline.** `tests/test_github_state.py` and `tests/test_brainstorm.py` must exist (or be created) with mocked `GitHubClient` patterns matching the existing test style. New tests required:
  - `test_list_features_synthesizes_raw_issue`
  - `test_list_features_dedup_raw_vs_initialized`
  - `test_patch_existing_issue_replaces_block`
  - `test_patch_existing_issue_appends_block_when_absent`
  - `test_patch_existing_issue_idempotent`
  - `test_convert_raw_issue_happy_path`
  - `test_convert_raw_issue_branch_already_exists`
  - `test_convert_raw_issue_no_match_raises_value_error`
  - `test_enqueue_planner_github_preflight_converts_raw`
  - `test_enqueue_planner_github_skips_preflight_when_initialized`
  - `test_enqueue_planner_azure_unchanged`
  - `test_feature_state_is_raw_property`
  - `test_slug_title_matches_convertforagent_algorithm`

No data migration, no infra change, no config change.
```