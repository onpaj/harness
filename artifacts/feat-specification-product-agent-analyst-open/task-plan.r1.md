# Product Agent — Analyst Open Questions Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded analyst↔product loop so that when the analyst emits a spec with open questions, an Opus-powered product agent answers them and the analyst re-runs with the answers folded in.

**Architecture:** Pure structural extension of the existing dispatcher state machine. Adds one `FeatureStatus` value (`questioning`), one agent definition (`.agents/product.md`), one queue (`product-queue`), two `PipelineConfig` fields (cap + counter), and a conditional branch in `dispatch_after_completion` that parses an analyst-emitted `## Status:` line. Counter increments under the existing state-update lease. Spec revision numbers stop being hard-coded `1` — the latest revision is `current_analyst_iteration + 1`.

**Tech Stack:** Python 3.11, Pydantic, pytest-asyncio, Textual (TUI), Anthropic Claude API. Existing primitives (`storage.py`, `prompt_builder.py`, `run_task.py`, queue/artifact backends) are not modified.

---

## File Structure

**New files:**
- `.agents/product.md` — product agent definition (frontmatter + system prompt)
- `docs/superpowers/plans/2026-04-29-product-agent-analyst-open-questions-loop.md` — this plan

**Modified files:**
- `agentharness/models.py` — `FeatureStatus.questioning`, `PipelineConfig` fields, `with_analyst_iteration_incremented()`
- `agentharness/github_labels.py` — `FEAT_QUESTIONING`, `QUEUE_PRODUCT`
- `agentharness/config.py` — top-level `max_analyst_iterations` field
- `agentharness/brainstorm.py` — propagate `max_analyst_iterations` into PipelineConfig on creation
- `agentharness/observer.py` — same propagation in observer-driven creation path
- `agentharness/dispatcher.py` — parser, helpers, dispatchers, branches, signature change, hard-coded `revision=1` removal
- `agentharness/tui.py` — icon/color/order/iteration counter in TaskPanel
- `agentharness/tui_state_change.py` — canonical state order
- `.pipeline/config.json` — `product-queue` entry, top-level `max_analyst_iterations: 2`
- `.agents/analyst.md` — system prompt addition (status contract + answers reading)

**Modified test files:**
- `tests/test_models.py` — counter helper, deserialization of new fields
- `tests/test_dispatcher.py` — parser, helpers, all new dispatch branches, signature change
- `tests/test_config.py` — `max_analyst_iterations` defaults
- `tests/test_tui_state_change.py` — canonical order includes `questioning`

---

## Task 1: Add `questioning` enum value to `FeatureStatus`

**Files:**
- Modify: `agentharness/models.py:12-23`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
class TestQuestioningEnumValue:
    def test_questioning_is_a_valid_status(self):
        assert FeatureStatus("questioning") == FeatureStatus.questioning

    def test_questioning_serialises_to_string(self):
        state = FeatureState(feature_id="feat-q", status=FeatureStatus.questioning)
        payload = state.model_dump_json()
        assert '"status":"questioning"' in payload

    def test_questioning_round_trips_through_json(self):
        state = FeatureState(feature_id="feat-q", status=FeatureStatus.questioning)
        restored = FeatureState.model_validate_json(state.model_dump_json())
        assert restored.status == FeatureStatus.questioning
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py::TestQuestioningEnumValue -v`
Expected: FAIL with `ValueError: 'questioning' is not a valid FeatureStatus`.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/models.py:12-23`:

```python
class FeatureStatus(str, Enum):
    brainstorming = "brainstorming"
    brainstormed = "brainstormed"
    analyzing = "analyzing"
    questioning = "questioning"
    architecting = "architecting"
    designing = "designing"
    planning = "planning"
    developing = "developing"
    reviewing = "reviewing"
    dev_revision = "dev_revision"
    done = "done"
    failed = "failed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_models.py::TestQuestioningEnumValue -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_models.py
git commit -m "feat: add FeatureStatus.questioning enum value"
```

---

## Task 2: Add cap + counter fields to `PipelineConfig`

**Files:**
- Modify: `agentharness/models.py:94-96`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError
from agentharness.models import PipelineConfig


class TestPipelineConfigAnalystFields:
    def test_defaults(self):
        cfg = PipelineConfig()
        assert cfg.max_analyst_iterations == 2
        assert cfg.current_analyst_iteration == 0

    def test_explicit_values(self):
        cfg = PipelineConfig(max_analyst_iterations=5, current_analyst_iteration=3)
        assert cfg.max_analyst_iterations == 5
        assert cfg.current_analyst_iteration == 3

    def test_zero_max_iterations_allowed(self):
        cfg = PipelineConfig(max_analyst_iterations=0)
        assert cfg.max_analyst_iterations == 0

    def test_negative_max_iterations_rejected(self):
        with pytest.raises(ValidationError):
            PipelineConfig(max_analyst_iterations=-1)

    def test_negative_current_iteration_rejected(self):
        with pytest.raises(ValidationError):
            PipelineConfig(current_analyst_iteration=-1)

    def test_legacy_state_json_without_new_fields_deserializes(self):
        legacy_cfg_json = '{"max_revisions": 3, "current_revision_round": 0}'
        cfg = PipelineConfig.model_validate_json(legacy_cfg_json)
        assert cfg.max_analyst_iterations == 2
        assert cfg.current_analyst_iteration == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py::TestPipelineConfigAnalystFields -v`
Expected: FAIL — fields don't exist yet.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/models.py:94-96`:

```python
class PipelineConfig(BaseModel):
    max_revisions: int = 3
    current_revision_round: int = 0
    max_analyst_iterations: int = Field(default=2, ge=0)
    current_analyst_iteration: int = Field(default=0, ge=0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_models.py::TestPipelineConfigAnalystFields -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_models.py
git commit -m "feat: add max/current analyst iteration fields to PipelineConfig"
```

---

## Task 3: Add `with_analyst_iteration_incremented()` helper to `FeatureState`

**Files:**
- Modify: `agentharness/models.py` (add method after `with_status`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
import time


class TestWithAnalystIterationIncremented:
    def _state(self, current: int = 0) -> FeatureState:
        return FeatureState(
            feature_id="feat-it",
            config=PipelineConfig(current_analyst_iteration=current),
        )

    def test_increments_counter_by_one(self):
        state = self._state(current=0)
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.current_analyst_iteration == 1

    def test_subsequent_increment_continues(self):
        state = self._state(current=1)
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.current_analyst_iteration == 2

    def test_original_state_unchanged(self):
        state = self._state(current=0)
        state.with_analyst_iteration_incremented()
        assert state.config.current_analyst_iteration == 0

    def test_max_iterations_preserved(self):
        state = FeatureState(
            feature_id="feat-it",
            config=PipelineConfig(max_analyst_iterations=5, current_analyst_iteration=2),
        )
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.max_analyst_iterations == 5
        assert updated.config.current_analyst_iteration == 3

    def test_other_fields_preserved(self):
        state = FeatureState(
            feature_id="feat-it",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        updated = state.with_analyst_iteration_incremented()
        assert updated.feature_id == "feat-it"
        assert updated.status == FeatureStatus.questioning

    def test_updated_at_advances(self):
        state = self._state(current=0)
        original = state.updated_at
        time.sleep(0.001)
        updated = state.with_analyst_iteration_incremented()
        assert updated.updated_at > original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py::TestWithAnalystIterationIncremented -v`
Expected: FAIL — `AttributeError: 'FeatureState' object has no attribute 'with_analyst_iteration_incremented'`.

- [ ] **Step 3: Write minimal implementation**

Add method to `FeatureState` in `agentharness/models.py` (place after `with_status`, around line 124):

```python
    def with_analyst_iteration_incremented(self) -> FeatureState:
        """Return new state with config.current_analyst_iteration += 1."""
        new_config = self.config.model_copy(
            update={"current_analyst_iteration": self.config.current_analyst_iteration + 1}
        )
        return self.model_copy(update={"config": new_config, "updated_at": datetime.now(UTC)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_models.py::TestWithAnalystIterationIncremented -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_models.py
git commit -m "feat: add FeatureState.with_analyst_iteration_incremented helper"
```

---

## Task 4: Add `feat:questioning` and `queue:product` GitHub labels

**Files:**
- Modify: `agentharness/github_labels.py`
- Test: append to existing `tests/test_github_state.py` or create new test in `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_github_labels.py` (new file):

```python
"""Round-trip tests for GitHub label constants."""

from agentharness.github_labels import (
    FEAT_QUESTIONING,
    FEAT_STATUS_LABELS,
    FEATURE_STATUS_TO_LABEL,
    LABEL_TO_FEATURE_STATUS,
    LABEL_TO_QUEUE_NAME,
    QUEUE_NAME_TO_LABEL,
    QUEUE_PRODUCT,
)
from agentharness.models import FeatureStatus


class TestQuestioningLabels:
    def test_feat_questioning_constant(self):
        assert FEAT_QUESTIONING == "feat:questioning"

    def test_queue_product_constant(self):
        assert QUEUE_PRODUCT == "queue:product"

    def test_feat_questioning_in_status_labels(self):
        assert FEAT_QUESTIONING in FEAT_STATUS_LABELS

    def test_feature_status_to_label_round_trip(self):
        assert FEATURE_STATUS_TO_LABEL[FeatureStatus.questioning] == FEAT_QUESTIONING
        assert LABEL_TO_FEATURE_STATUS[FEAT_QUESTIONING] == FeatureStatus.questioning

    def test_queue_name_round_trip(self):
        assert QUEUE_NAME_TO_LABEL["product-queue"] == QUEUE_PRODUCT
        assert LABEL_TO_QUEUE_NAME[QUEUE_PRODUCT] == "product-queue"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_github_labels.py -v`
Expected: FAIL — `ImportError: cannot import name 'FEAT_QUESTIONING' from 'agentharness.github_labels'`.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/github_labels.py`:

After `FEAT_DEV_REVISION = "feat:dev_revision"` (around line 22) add:
```python
FEAT_QUESTIONING = "feat:questioning"
```

In the `FEAT_STATUS_LABELS = frozenset({...})` literal (around line 25-37) add `FEAT_QUESTIONING` to the set.

After `QUEUE_REVIEWER = "queue:reviewer"` (around line 68) add:
```python
QUEUE_PRODUCT = "queue:product"
```

In the `QUEUE_NAME_TO_LABEL = {...}` dict (around line 70-77) add:
```python
    "product-queue": QUEUE_PRODUCT,
```

In the `FEATURE_STATUS_TO_LABEL = {...}` dict (around line 104-116) add:
```python
    FeatureStatus.questioning: FEAT_QUESTIONING,
```

(Both `LABEL_TO_QUEUE_NAME` and `LABEL_TO_FEATURE_STATUS` are derived dict comprehensions and require no edit.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_labels.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_labels.py tests/test_github_labels.py
git commit -m "feat: add feat:questioning and queue:product GitHub labels"
```

---

## Task 5: Add `max_analyst_iterations` to top-level `Config`

**Files:**
- Modify: `agentharness/config.py:104-113`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
import json
from pathlib import Path
from agentharness.config import Config, load_config


class TestMaxAnalystIterationsConfig:
    def test_default_value_is_two(self):
        cfg = Config()
        assert cfg.max_analyst_iterations == 2

    def test_load_config_uses_default_when_absent(self, tmp_path):
        config_dir = tmp_path / ".pipeline"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "storage_backend": "azure",
            "queues": {},
        }))
        cfg = load_config(config_file)
        assert cfg.max_analyst_iterations == 2

    def test_load_config_reads_explicit_value(self, tmp_path):
        config_dir = tmp_path / ".pipeline"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "storage_backend": "azure",
            "queues": {},
            "max_analyst_iterations": 5,
        }))
        cfg = load_config(config_file)
        assert cfg.max_analyst_iterations == 5

    def test_load_config_zero_disables_loop(self, tmp_path):
        config_dir = tmp_path / ".pipeline"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "storage_backend": "azure",
            "queues": {},
            "max_analyst_iterations": 0,
        }))
        cfg = load_config(config_file)
        assert cfg.max_analyst_iterations == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::TestMaxAnalystIterationsConfig -v`
Expected: FAIL — `Config` has no `max_analyst_iterations` attribute.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/config.py:104-113`. Add field to `Config`:

```python
class Config(BaseModel):
    storage: StorageConfig = StorageConfig()
    github: GitHubConfig = GitHubConfig()
    storage_backend: str = "azure"  # "azure" | "github"
    queues: dict[str, QueueConfig] = {}
    defaults: DefaultsConfig = DefaultsConfig()
    config_dir: Path = Path(".")
    use_worktrees: bool = False
    worktree_base_dir: str = ".worktrees"
    worktree_base_branch: str | None = None
    max_analyst_iterations: int = 2
```

(Pydantic ignores unknown JSON keys by default, but `Config` uses standard `BaseModel` which permits extra fields silently — this addition is purely additive.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py::TestMaxAnalystIterationsConfig -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/config.py tests/test_config.py
git commit -m "feat: add max_analyst_iterations field to top-level Config"
```

---

## Task 6: Propagate `max_analyst_iterations` into `PipelineConfig` on feature creation

**Files:**
- Modify: `agentharness/brainstorm.py:163`
- Modify: `agentharness/observer.py:283`
- Test: `tests/test_brainstorm_github.py` (or create a brainstorm-only unit test)

- [ ] **Step 1: Write the failing test**

Create `tests/test_brainstorm_pipeline_config.py`:

```python
"""brainstorm.py and observer.py copy max_analyst_iterations into FeatureState.config."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.config import Config, DefaultsConfig
from agentharness.models import FeatureState, FeatureStatus, PipelineConfig


@pytest.mark.asyncio
async def test_brainstorm_uploads_state_with_max_analyst_iterations():
    from agentharness.brainstorm import upload_brief

    config = Config(
        storage_backend="azure",
        defaults=DefaultsConfig(max_revisions=4),
        max_analyst_iterations=7,
    )

    captured: dict = {}

    async def fake_create(state: FeatureState, **_):
        captured["state"] = state

    fake_state_mgr = MagicMock()
    fake_state_mgr.create = AsyncMock(side_effect=fake_create)

    fake_store = MagicMock()
    fake_store.upload = AsyncMock()
    fake_store.close = AsyncMock()

    with patch("agentharness.brainstorm.create_artifact_store", return_value=fake_store), \
         patch("agentharness.brainstorm.create_state_manager", return_value=fake_state_mgr):
        await upload_brief("feat-test", "# Brief\n\ncontent", config)

    state = captured["state"]
    assert state.config.max_revisions == 4
    assert state.config.max_analyst_iterations == 7
    assert state.config.current_analyst_iteration == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_brainstorm_pipeline_config.py -v`
Expected: FAIL — `state.config.max_analyst_iterations` is the default 2, not 7.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/brainstorm.py:163`:

```python
        initial_state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.brainstormed,
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
                max_analyst_iterations=config.max_analyst_iterations,
            ),
            branch_name=branch_name,
        ).with_event("brief_uploaded")
```

Edit `agentharness/observer.py:283` analogously:

```python
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
                max_analyst_iterations=config.max_analyst_iterations,
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brainstorm_pipeline_config.py tests/test_brainstorm_github.py -v`
Expected: All passing (existing brainstorm-github tests use the default 2, which still matches).

- [ ] **Step 5: Commit**

```bash
git add agentharness/brainstorm.py agentharness/observer.py tests/test_brainstorm_pipeline_config.py
git commit -m "feat: propagate max_analyst_iterations into FeatureState.config on creation"
```

---

## Task 7: Add `_parse_analyst_status` helper

**Files:**
- Modify: `agentharness/dispatcher.py` (add helper near `_parse_developer_status`, around line 378)
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
class TestParseAnalystStatus:
    def test_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec\n\n## Status: COMPLETE\n") == "COMPLETE"

    def test_has_questions(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec\n\n## Status: HAS_QUESTIONS\n") == "HAS_QUESTIONS"

    def test_missing_status_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec body without status line.") == "COMPLETE"

    def test_empty_string_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("") == "COMPLETE"

    def test_lowercase_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: has_questions\n") == "COMPLETE"

    def test_mixed_case_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: Has_Questions\n") == "COMPLETE"

    def test_garbage_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: WAT\n") == "COMPLETE"

    def test_status_at_end_of_file_no_trailing_newline(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("body\n## Status: HAS_QUESTIONS") == "HAS_QUESTIONS"

    def test_extra_whitespace_around_value(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status:   HAS_QUESTIONS  \n") == "HAS_QUESTIONS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestParseAnalystStatus -v`
Expected: FAIL — `ImportError: cannot import name '_parse_analyst_status'`.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py`. Below the existing `_DEV_STATUS_RE` definition (around line 373) add:

```python
_ANALYST_STATUS_RE = re.compile(
    r"^##\s+Status:\s*(\S+)\s*$", re.MULTILINE
)


def _parse_analyst_status(output: str) -> str:
    """Parse analyst's '## Status:' line. Safe default: COMPLETE.

    Returns 'HAS_QUESTIONS' only when the captured value is exactly
    'HAS_QUESTIONS' (case-sensitive). Any other outcome — missing line,
    different keyword, lowercase variant — returns 'COMPLETE'.
    """
    match = _ANALYST_STATUS_RE.search(output)
    if match and match.group(1) == "HAS_QUESTIONS":
        return "HAS_QUESTIONS"
    return "COMPLETE"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestParseAnalystStatus -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _parse_analyst_status helper to dispatcher"
```

---

## Task 8: Add `_latest_spec_revision` helper

**Files:**
- Modify: `agentharness/dispatcher.py`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
class TestLatestSpecRevision:
    def test_initial_state_returns_one(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import FeatureState, PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=0),
        )
        assert _latest_spec_revision(state) == 1

    def test_after_one_increment_returns_two(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import FeatureState, PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=1),
        )
        assert _latest_spec_revision(state) == 2

    def test_after_two_increments_returns_three(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import FeatureState, PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=2),
        )
        assert _latest_spec_revision(state) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestLatestSpecRevision -v`
Expected: FAIL — `ImportError: cannot import name '_latest_spec_revision'`.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py`. After `_parse_analyst_status` add:

```python
def _latest_spec_revision(state: FeatureState) -> int:
    """Return the revision number of the most recent (or upcoming) spec.

    Invariant: at the moment the analyst runs, its output revision equals
    `current_analyst_iteration + 1`. This helper centralizes the rule so
    every spec consumer reads the latest revision instead of a hard-coded 1.
    """
    return state.config.current_analyst_iteration + 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestLatestSpecRevision -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _latest_spec_revision helper to dispatcher"
```

---

## Task 9: Change `_artifacts_for_phase` signature and add `analyzing` accumulator + `questioning`

**Files:**
- Modify: `agentharness/dispatcher.py:415-433` (function body)
- Modify: `agentharness/dispatcher.py:149` (caller in `_dispatch_linear`)
- Modify: `agentharness/dispatcher.py:544` (caller in `build_phase_task`)
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
class TestArtifactsForPhase:
    def _state(self, current: int, status: FeatureStatus = FeatureStatus.analyzing) -> FeatureState:
        from agentharness.models import PipelineConfig
        return FeatureState(
            feature_id="feat-a",
            status=status,
            config=PipelineConfig(current_analyst_iteration=current),
        )

    def test_analyzing_initial_returns_brief_only(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == ["artifacts/feat-a/brief.md"]

    def test_analyzing_after_one_loop_includes_spec_and_answers_r1(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
            "artifacts/feat-a/answers.r1.md",
        ]

    def test_analyzing_after_two_loops_includes_specs_and_answers_r1_r2(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
            "artifacts/feat-a/spec.r2.md",
            "artifacts/feat-a/answers.r1.md",
            "artifacts/feat-a/answers.r2.md",
        ]

    def test_questioning_first_iteration_includes_spec_r1_no_answers(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0, status=FeatureStatus.questioning)
        artifacts = _artifacts_for_phase(state, "questioning")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
        ]

    def test_questioning_second_iteration_includes_spec_r2_and_answers_r1(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1, status=FeatureStatus.questioning)
        artifacts = _artifacts_for_phase(state, "questioning")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r2.md",
            "artifacts/feat-a/answers.r1.md",
        ]

    def test_architecting_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "architecting")
        assert "artifacts/feat-a/spec.r3.md" in artifacts
        assert "artifacts/feat-a/brief.md" in artifacts

    def test_designing_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1)
        artifacts = _artifacts_for_phase(state, "designing")
        assert "artifacts/feat-a/spec.r2.md" in artifacts
        assert "artifacts/feat-a/arch-review.r1.md" in artifacts

    def test_planning_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "planning")
        assert "artifacts/feat-a/spec.r3.md" in artifacts
        assert "artifacts/feat-a/design.r1.md" in artifacts

    def test_unknown_phase_returns_empty_list(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0)
        assert _artifacts_for_phase(state, "nonexistent") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestArtifactsForPhase -v`
Expected: FAIL — current signature is `(feature_id, phase)` and questioning isn't handled.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py:415-433`. Replace `_artifacts_for_phase` body with:

```python
def _artifacts_for_phase(state: FeatureState, phase: str) -> list[str]:
    """Return input artifact paths for a given pipeline phase.

    Takes the full FeatureState so the analyst-loop accumulator can read
    `current_analyst_iteration` and assemble all completed prior specs and
    answers.
    """
    feature_id = state.feature_id
    iter_n = state.config.current_analyst_iteration
    spec_rev = _latest_spec_revision(state)  # = iter_n + 1

    if phase == "analyzing":
        artifacts = [f"artifacts/{feature_id}/brief.md"]
        artifacts += [phase_artifact_path(feature_id, "spec", i) for i in range(1, spec_rev)]
        artifacts += [phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)]
        return artifacts

    if phase == "questioning":
        return [
            f"artifacts/{feature_id}/brief.md",
            phase_artifact_path(feature_id, "spec", spec_rev),
            *[phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)],
        ]

    latest_spec = phase_artifact_path(feature_id, "spec", spec_rev)
    if phase == "architecting":
        return [latest_spec, f"artifacts/{feature_id}/brief.md"]
    if phase == "designing":
        return [latest_spec, phase_artifact_path(feature_id, "arch-review", 1)]
    if phase == "planning":
        return [
            latest_spec,
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
        ]
    return []
```

Update the two callers of `_artifacts_for_phase`:

`agentharness/dispatcher.py:149` — in `_dispatch_linear`, change:
```python
    input_artifacts = _artifacts_for_phase(feature_id, next_status)
```
to:
```python
    input_artifacts = _artifacts_for_phase(state, next_status)
```

`agentharness/dispatcher.py:544` — in `build_phase_task`, change:
```python
    input_artifacts = _artifacts_for_phase(feature_id, phase)
```
to:
```python
    input_artifacts = _artifacts_for_phase(state, phase)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: All passing — both new `TestArtifactsForPhase` and existing `TestBuildPhaseTask` tests.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "refactor: take FeatureState in _artifacts_for_phase, support questioning + accumulator"
```

---

## Task 10: Replace remaining hard-coded `revision=1` for spec in dispatcher

**Files:**
- Modify: `agentharness/dispatcher.py:187` (in `_dispatch_fan_out`)
- Modify: `agentharness/dispatcher.py:260` (in `_enqueue_per_task_review`)
- Modify: `agentharness/dispatcher.py:336` (in `_dispatch_review_result`)
- Modify: `agentharness/dispatcher.py:530` (in `build_phase_task` reviewing branch)
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
class TestSpecRevisionInDispatchPaths:
    def test_fan_out_uses_latest_spec_when_iteration_is_two(self):
        """_dispatch_fan_out must consume spec.r3 (not r1) when current_analyst_iteration=2."""
        import asyncio
        from agentharness.dispatcher import _dispatch_fan_out
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-fanout",
            status=FeatureStatus.planning,
            config=PipelineConfig(current_analyst_iteration=2),
        )
        queues = _make_queues()
        cfg = _make_config()

        result = asyncio.get_event_loop().run_until_complete(
            _dispatch_fan_out(state, "## ignored\n", cfg, queues)
        )
        sent = queues["developer-queue"].send_task.call_args[0][0]
        assert "artifacts/feat-fanout/spec.r3.md" in sent.input_artifacts
        assert "artifacts/feat-fanout/spec.r1.md" not in sent.input_artifacts
        assert result.status == FeatureStatus.developing

    def test_review_task_uses_latest_spec(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig
        existing = TaskMessage(
            feature_id="feat-r",
            task_id="feat-r-dev-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-r/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=existing.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=existing.model_dump(),
        )
        state = FeatureState(
            feature_id="feat-r",
            status=FeatureStatus.reviewing,
            config=PipelineConfig(current_analyst_iteration=1),
        ).with_tasks_added([entry])

        cfg = MagicMock()
        from pathlib import Path
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "review-queue": Path(".agents/reviewer.md"),
        }[q]

        task = build_phase_task(state, FeatureStatus.reviewing, cfg)
        assert "artifacts/feat-r/spec.r2.md" in task.input_artifacts
        assert "artifacts/feat-r/spec.r1.md" not in task.input_artifacts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestSpecRevisionInDispatchPaths -v`
Expected: FAIL — current code uses `phase_artifact_path(feature_id, "spec", 1)`.

- [ ] **Step 3: Write minimal implementation**

In `agentharness/dispatcher.py`, replace these `phase_artifact_path(feature_id, "spec", 1)` references:

`_dispatch_fan_out` (line 187):
```python
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
            phase_artifact_path(feature_id, "task-plan", 1),
        ],
```

`_enqueue_per_task_review` (line 260):
```python
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
            phase_artifact_path(feature_id, "arch-review", 1),
            dev_task.output_artifact,
        ],
```

`build_phase_task` reviewing branch (line 530):
```python
            input_artifacts=[
                phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
                phase_artifact_path(feature_id, "arch-review", 1),
                dev_task.output_artifact,
            ],
```

`_dispatch_review_result` does **not** reference `spec.r1.md`. Verify with `grep -n 'spec", 1' agentharness/dispatcher.py` and confirm no `phase_artifact_path(.*"spec", 1)` remains. Note: `phase_artifact_path(feature_id, _output_name(phase), 1)` in `_dispatch_linear` (line 150) and `build_phase_task` (line 545) is the **output** path of the current phase, not a spec consumer — leave it alone for now (see Task 13 for further handling).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: All passing.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "refactor: use _latest_spec_revision in fan-out and review dispatch paths"
```

---

## Task 11: Add `STATE_TO_QUEUE[questioning]` entry

**Files:**
- Modify: `agentharness/dispatcher.py:83-95`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py` inside the existing `TestStateToQueue` class:

```python
    def test_questioning_routes_to_product_queue(self):
        from agentharness.dispatcher import STATE_TO_QUEUE, queue_for_state
        from agentharness.models import FeatureStatus
        assert STATE_TO_QUEUE[FeatureStatus.questioning] == "product-queue"
        assert queue_for_state(FeatureStatus.questioning) == "product-queue"

    def test_mapping_includes_questioning(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        from agentharness.models import FeatureStatus
        assert FeatureStatus.questioning in STATE_TO_QUEUE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestStateToQueue -v`
Expected: FAIL — questioning not in mapping.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py:83-95`:

```python
STATE_TO_QUEUE: dict[FeatureStatus, str | None] = {
    FeatureStatus.brainstorming: None,
    FeatureStatus.brainstormed:  None,
    FeatureStatus.analyzing:     "analyst-queue",
    FeatureStatus.questioning:   "product-queue",
    FeatureStatus.architecting:  "architect-queue",
    FeatureStatus.designing:     "designer-queue",
    FeatureStatus.planning:      "planner-queue",
    FeatureStatus.developing:    "developer-queue",
    FeatureStatus.dev_revision:  "developer-queue",
    FeatureStatus.reviewing:     "review-queue",
    FeatureStatus.done:          None,
    FeatureStatus.failed:        None,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestStateToQueue -v`
Expected: All passing.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: route questioning status to product-queue"
```

---

## Task 12: Implement `_dispatch_questioning`

**Files:**
- Modify: `agentharness/dispatcher.py` (add new dispatcher above `_dispatch_serial_next`)
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
def _make_questioning_queues() -> dict:
    q = AsyncMock()
    q.send_task = AsyncMock()
    return {"product-queue": q, "architect-queue": AsyncMock(), "developer-queue": AsyncMock(), "review-queue": AsyncMock(), "analyst-queue": AsyncMock()}


def _make_questioning_config() -> Config:
    cfg = MagicMock(spec=Config)
    cfg.storage_backend = "azure"
    from pathlib import Path
    cfg.agent_path_for_queue.side_effect = lambda q: {
        "product-queue": Path(".agents/product.md"),
        "analyst-queue": Path(".agents/analyst.md"),
        "architect-queue": Path(".agents/architect.md"),
    }[q]
    return cfg


@pytest.mark.asyncio
class TestDispatchQuestioning:
    async def test_enqueues_product_task_first_iteration(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
            state_issue_number=99,
        )
        queues = _make_questioning_queues()
        result = await _dispatch_questioning(state, _make_questioning_config(), queues)

        assert result.status == FeatureStatus.questioning
        queues["product-queue"].send_task.assert_awaited_once()
        sent = queues["product-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-q-questioning-r1"
        assert sent.agent_role == "product"
        assert sent.output_artifact == "artifacts/feat-q/answers.r1.md"
        assert "artifacts/feat-q/brief.md" in sent.input_artifacts
        assert "artifacts/feat-q/spec.r1.md" in sent.input_artifacts
        assert sent.state_issue_number == 99

    async def test_enqueues_product_task_second_iteration(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=1, max_analyst_iterations=2),
        )
        queues = _make_questioning_queues()
        result = await _dispatch_questioning(state, _make_questioning_config(), queues)

        sent = queues["product-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-q-questioning-r2"
        assert sent.output_artifact == "artifacts/feat-q/answers.r2.md"
        assert "artifacts/feat-q/spec.r2.md" in sent.input_artifacts
        assert "artifacts/feat-q/answers.r1.md" in sent.input_artifacts
        assert result.status == FeatureStatus.questioning

    async def test_emits_phase_enqueued_event(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        queues = _make_questioning_queues()
        result = await _dispatch_questioning(state, _make_questioning_config(), queues)

        events = [e for e in result.history if e.event == "phase_enqueued"]
        assert events and events[-1].phase == "questioning"

    async def test_raises_when_product_queue_missing(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig

        state = FeatureState(feature_id="feat-q", config=PipelineConfig())
        queues = {}  # no product-queue
        with pytest.raises(RuntimeError, match="product-queue"):
            await _dispatch_questioning(state, _make_questioning_config(), queues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestDispatchQuestioning -v`
Expected: FAIL — `_dispatch_questioning` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py`. Add new function above `_dispatch_serial_next` (around line 215):

```python
async def _dispatch_questioning(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Enqueue the product agent to answer open questions in the latest spec."""
    product_queue = queues.get("product-queue")
    if not product_queue:
        raise RuntimeError("product-queue not found")

    feature_id = state.feature_id
    spec_rev = _latest_spec_revision(state)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-questioning-r{spec_rev}",
        input_artifacts=_artifacts_for_phase(state, "questioning"),
        output_artifact=phase_artifact_path(feature_id, "answers", spec_rev),
        agent_role="product",
        state_issue_number=state.state_issue_number,
    )
    await product_queue.send_task(task)
    log.info("Enqueued product task %s for feature %s", task.task_id, feature_id)

    return (
        state
        .with_status(FeatureStatus.questioning)
        .with_phase("questioning", PhaseInfo(status=PhaseStatus.pending))
        .with_event("phase_enqueued", phase="questioning")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestDispatchQuestioning -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: implement _dispatch_questioning to enqueue product agent"
```

---

## Task 13: Implement `_dispatch_analyst_rerun`

**Files:**
- Modify: `agentharness/dispatcher.py` (add after `_dispatch_questioning`)
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
@pytest.mark.asyncio
class TestDispatchAnalystRerun:
    async def test_increments_counter_and_enqueues_analyst(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-rr",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
            state_issue_number=12,
        )
        queues = _make_questioning_queues()
        cfg = _make_questioning_config()

        result = await _dispatch_analyst_rerun(state, cfg, queues)

        assert result.config.current_analyst_iteration == 1
        assert result.status == FeatureStatus.analyzing
        queues["analyst-queue"].send_task.assert_awaited_once()
        sent = queues["analyst-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-rr-analyzing-r2"
        assert sent.output_artifact == "artifacts/feat-rr/spec.r2.md"
        assert sent.agent_role == "analyst"
        assert "artifacts/feat-rr/brief.md" in sent.input_artifacts
        assert "artifacts/feat-rr/spec.r1.md" in sent.input_artifacts
        assert "artifacts/feat-rr/answers.r1.md" in sent.input_artifacts
        assert sent.state_issue_number == 12

    async def test_third_iteration_passes_two_specs_two_answers(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-rr",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=1, max_analyst_iterations=3),
        )
        queues = _make_questioning_queues()
        result = await _dispatch_analyst_rerun(state, _make_questioning_config(), queues)

        assert result.config.current_analyst_iteration == 2
        sent = queues["analyst-queue"].send_task.call_args[0][0]
        assert sent.output_artifact == "artifacts/feat-rr/spec.r3.md"
        assert "artifacts/feat-rr/spec.r1.md" in sent.input_artifacts
        assert "artifacts/feat-rr/spec.r2.md" in sent.input_artifacts
        assert "artifacts/feat-rr/answers.r1.md" in sent.input_artifacts
        assert "artifacts/feat-rr/answers.r2.md" in sent.input_artifacts

    async def test_emits_phase_enqueued_event(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-rr",
            config=PipelineConfig(current_analyst_iteration=0),
        )
        queues = _make_questioning_queues()
        result = await _dispatch_analyst_rerun(state, _make_questioning_config(), queues)

        events = [e for e in result.history if e.event == "phase_enqueued"]
        assert events and events[-1].phase == "analyzing"

    async def test_raises_when_analyst_queue_missing(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig

        state = FeatureState(feature_id="feat-rr", config=PipelineConfig())
        queues = {}
        with pytest.raises(RuntimeError, match="analyst-queue"):
            await _dispatch_analyst_rerun(state, _make_questioning_config(), queues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestDispatchAnalystRerun -v`
Expected: FAIL — `_dispatch_analyst_rerun` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py`. Add after `_dispatch_questioning`:

```python
async def _dispatch_analyst_rerun(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Increment the analyst iteration counter and re-enqueue the analyst task.

    The increment is applied to the in-memory state here; callers persist
    the returned state inside their state_mgr.update lease so the change
    is exactly-once across observer crash + replay.
    """
    analyst_queue = queues.get("analyst-queue")
    if not analyst_queue:
        raise RuntimeError("analyst-queue not found")

    incremented = state.with_analyst_iteration_incremented()
    feature_id = incremented.feature_id
    spec_rev = _latest_spec_revision(incremented)  # iter+1 after increment

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-analyzing-r{spec_rev}",
        input_artifacts=_artifacts_for_phase(incremented, "analyzing"),
        output_artifact=phase_artifact_path(feature_id, "spec", spec_rev),
        agent_role="analyst",
        state_issue_number=incremented.state_issue_number,
    )
    await analyst_queue.send_task(task)
    log.info("Re-enqueued analyst task %s for feature %s (iter=%d)",
             task.task_id, feature_id, incremented.config.current_analyst_iteration)

    return (
        incremented
        .with_status(FeatureStatus.analyzing)
        .with_phase("analyzing", PhaseInfo(status=PhaseStatus.pending))
        .with_event("phase_enqueued", phase="analyzing", details=f"analyst iteration {incremented.config.current_analyst_iteration}")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestDispatchAnalystRerun -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: implement _dispatch_analyst_rerun with atomic counter increment"
```

---

## Task 14: Wire branches into `dispatch_after_completion` and remove `_LINEAR_TRANSITIONS["analyzing"]`

**Files:**
- Modify: `agentharness/dispatcher.py:74-78`
- Modify: `agentharness/dispatcher.py:104-131`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
@pytest.mark.asyncio
class TestDispatchAfterCompletionAnalyzing:
    def _state(self, current: int = 0, max_iter: int = 2) -> FeatureState:
        from agentharness.models import PipelineConfig
        return FeatureState(
            feature_id="feat-d",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(
                current_analyst_iteration=current,
                max_analyst_iterations=max_iter,
            ),
        )

    def _analyst_task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-d",
            task_id="feat-d-analyzing-r1",
            input_artifacts=["artifacts/feat-d/brief.md"],
            output_artifact="artifacts/feat-d/spec.r1.md",
            agent_role="analyst",
        )

    async def test_complete_status_transitions_to_architecting(self):
        from agentharness.dispatcher import dispatch_after_completion

        state = self._state()
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec body\n\n## Status: COMPLETE\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.architecting
        queues["architect-queue"].send_task.assert_awaited_once()
        queues["product-queue"].send_task.assert_not_awaited()

    async def test_has_questions_under_cap_transitions_to_questioning(self):
        from agentharness.dispatcher import dispatch_after_completion

        state = self._state(current=0, max_iter=2)
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec body\n\n## Status: HAS_QUESTIONS\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.questioning
        queues["product-queue"].send_task.assert_awaited_once()
        queues["architect-queue"].send_task.assert_not_awaited()

    async def test_has_questions_at_cap_transitions_to_architecting(self, caplog):
        import logging
        from agentharness.dispatcher import dispatch_after_completion

        state = self._state(current=2, max_iter=2)
        queues = _make_questioning_queues()
        with caplog.at_level(logging.WARNING, logger="agentharness.dispatcher"):
            result = await dispatch_after_completion(
                state, self._analyst_task(), "spec body\n\n## Status: HAS_QUESTIONS\n",
                _make_questioning_config(), queues,
            )
        assert result.status == FeatureStatus.architecting
        queues["product-queue"].send_task.assert_not_awaited()
        assert any("max_analyst_iterations cap reached" in r.message for r in caplog.records)

    async def test_cap_zero_disables_loop(self):
        """max_analyst_iterations=0 should always proceed to architecting."""
        from agentharness.dispatcher import dispatch_after_completion

        state = self._state(current=0, max_iter=0)
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec\n\n## Status: HAS_QUESTIONS\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.architecting
        queues["product-queue"].send_task.assert_not_awaited()

    async def test_questioning_complete_transitions_to_analyzing_with_increment(self):
        from agentharness.dispatcher import dispatch_after_completion

        state = FeatureState(
            feature_id="feat-d",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
        )
        product_task = TaskMessage(
            feature_id="feat-d",
            task_id="feat-d-questioning-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-d/answers.r1.md",
            agent_role="product",
        )
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, product_task, "### Question 1\n... answers ...\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.analyzing
        assert result.config.current_analyst_iteration == 1
        queues["analyst-queue"].send_task.assert_awaited_once()


def test_linear_transitions_no_longer_includes_analyzing():
    from agentharness.dispatcher import _LINEAR_TRANSITIONS
    assert "analyzing" not in _LINEAR_TRANSITIONS
```

(Add `from agentharness.models import PipelineConfig` at the import block at the top of the test file if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestDispatchAfterCompletionAnalyzing tests/test_dispatcher.py::test_linear_transitions_no_longer_includes_analyzing -v`
Expected: FAIL — `_LINEAR_TRANSITIONS["analyzing"]` still present and `dispatch_after_completion` still falls through to `_dispatch_linear` for analyzing.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/dispatcher.py:74-78`. Replace:

```python
_LINEAR_TRANSITIONS: dict[str, tuple[str, str]] = {
    "analyzing": ("architecting", "architect-queue"),
    "architecting": ("designing", "designer-queue"),
    "designing": ("planning", "planner-queue"),
}
```

with:

```python
_LINEAR_TRANSITIONS: dict[str, tuple[str, str]] = {
    "architecting": ("designing", "designer-queue"),
    "designing": ("planning", "planner-queue"),
}
```

Edit `agentharness/dispatcher.py:104-131`. Replace `dispatch_after_completion` with:

```python
async def dispatch_after_completion(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
) -> FeatureState | None:
    """Determine and execute the next pipeline step.

    Returns the updated FeatureState, or None if no further action (fan-in wait).
    """
    status = state.status

    if status == FeatureStatus.analyzing:
        analyst_status = _parse_analyst_status(agent_output)
        cfg = state.config
        cap_reached = cfg.current_analyst_iteration >= cfg.max_analyst_iterations
        if analyst_status == "COMPLETE" or cap_reached:
            if analyst_status == "HAS_QUESTIONS" and cap_reached:
                log.warning(
                    "max_analyst_iterations cap reached — proceeding to architecting "
                    "(feature_id=%s, current=%d, max=%d)",
                    state.feature_id,
                    cfg.current_analyst_iteration,
                    cfg.max_analyst_iterations,
                )
            return await _dispatch_linear_to(state, "analyzing", "architecting", "architect-queue", config, queues)
        return await _dispatch_questioning(state, config, queues)

    if status == FeatureStatus.questioning:
        return await _dispatch_analyst_rerun(state, config, queues)

    if status in (FeatureStatus.architecting, FeatureStatus.designing):
        return await _dispatch_linear(state, status, config, queues)

    if status == FeatureStatus.planning:
        return await _dispatch_fan_out(state, agent_output, config, queues)

    if status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        return await _dispatch_serial_next(state, completed_task, agent_output, config, queues, state_mgr)

    if status == FeatureStatus.reviewing:
        return await _dispatch_review_result(state, completed_task, agent_output, config, queues, state_mgr)

    log.warning("No dispatch logic for status %r", status)
    return None
```

Add the `_dispatch_linear_to` helper near `_dispatch_linear` (after line 169) — it lets the caller specify the explicit next status when the transition is no longer in `_LINEAR_TRANSITIONS`:

```python
async def _dispatch_linear_to(
    state: FeatureState,
    current_status: str,
    next_status: str,
    queue_key: str,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Same as _dispatch_linear but with an explicit destination — used by
    the analyzing→architecting fallback path when the analyst signals COMPLETE
    or the iteration cap is reached."""
    next_queue = queues.get(queue_key)
    if not next_queue:
        raise RuntimeError(f"Queue {queue_key!r} not found")

    agent_path = config.agent_path_for_queue(queue_key)
    feature_id = state.feature_id

    input_artifacts = _artifacts_for_phase(state, next_status)
    output_artifact = phase_artifact_path(feature_id, _output_name(next_status), 1)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-{next_status}-1",
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_path.stem,
        state_issue_number=state.state_issue_number,
    )
    await next_queue.send_task(task)
    log.info("Enqueued %s task for feature %s", next_status, feature_id)

    phase_info = PhaseInfo(status=PhaseStatus.pending)
    return (
        state
        .with_status(FeatureStatus(next_status))
        .with_phase(next_status, phase_info)
        .with_event("phase_enqueued", phase=next_status)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: All passing — new `TestDispatchAfterCompletionAnalyzing` (5 tests), the `test_linear_transitions_no_longer_includes_analyzing` standalone, and existing tests untouched.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: branch dispatch_after_completion on analyst status and iteration cap"
```

---

## Task 15: Update `build_phase_task` for `questioning` phase

**Files:**
- Modify: `agentharness/dispatcher.py:473-554`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
class TestBuildPhaseTaskQuestioning:
    def _config(self):
        cfg = MagicMock()
        from pathlib import Path
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "analyst-queue":   Path(".agents/analyst.md"),
            "product-queue":   Path(".agents/product.md"),
            "architect-queue": Path(".agents/architect.md"),
            "designer-queue":  Path(".agents/designer.md"),
            "planner-queue":   Path(".agents/planner.md"),
            "developer-queue": Path(".agents/developer.md"),
            "review-queue":    Path(".agents/reviewer.md"),
        }[q]
        return cfg

    def test_questioning_builds_product_task(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-bq",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        task = build_phase_task(state, FeatureStatus.questioning, self._config())
        assert task.task_id == "feat-bq-questioning-r1"
        assert task.agent_role == "product"
        assert task.output_artifact == "artifacts/feat-bq/answers.r1.md"
        assert "artifacts/feat-bq/spec.r1.md" in task.input_artifacts

    def test_questioning_second_iteration(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-bq",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=1),
        )
        task = build_phase_task(state, FeatureStatus.questioning, self._config())
        assert task.task_id == "feat-bq-questioning-r2"
        assert task.output_artifact == "artifacts/feat-bq/answers.r2.md"
        assert "artifacts/feat-bq/spec.r2.md" in task.input_artifacts
        assert "artifacts/feat-bq/answers.r1.md" in task.input_artifacts

    def test_analyzing_uses_revision_aware_output(self):
        """build_phase_task for analyzing must produce spec.r{N+1} when iter=N."""
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-ba",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=1),
        )
        task = build_phase_task(state, FeatureStatus.analyzing, self._config())
        assert task.output_artifact == "artifacts/feat-ba/spec.r2.md"
        assert task.task_id == "feat-ba-analyzing-r2"

    def test_analyzing_first_pass_uses_r1(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig

        state = FeatureState(
            feature_id="feat-ba",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        task = build_phase_task(state, FeatureStatus.analyzing, self._config())
        assert task.output_artifact == "artifacts/feat-ba/spec.r1.md"
        assert task.task_id == "feat-ba-analyzing-r1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestBuildPhaseTaskQuestioning -v`
Expected: FAIL — questioning isn't recognised as a phase agent and the analyzing path uses revision=1.

- [ ] **Step 3: Write minimal implementation**

Edit the phase-agents fall-through in `build_phase_task` (`agentharness/dispatcher.py:541-554`):

```python
    # Phase agents: analyzing, questioning, architecting, designing, planning
    phase = target_status.value
    input_artifacts = _artifacts_for_phase(state, phase)

    if phase == "analyzing":
        spec_rev = _latest_spec_revision(state)
        output_artifact = phase_artifact_path(feature_id, "spec", spec_rev)
        task_id = f"{feature_id}-analyzing-r{spec_rev}"
    elif phase == "questioning":
        spec_rev = _latest_spec_revision(state)
        output_artifact = phase_artifact_path(feature_id, "answers", spec_rev)
        task_id = f"{feature_id}-questioning-r{spec_rev}"
    else:
        output_artifact = phase_artifact_path(feature_id, _output_name(phase), 1)
        task_id = f"{feature_id}-{phase}-1"

    agent_role = config.agent_path_for_queue(queue_name).stem
    return TaskMessage(
        feature_id=feature_id,
        task_id=task_id,
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_role,
        state_issue_number=state.state_issue_number,
    )
```

Note: the existing test `test_phase_agent_task_for_analyzing` expects `task_id="feat-x-analyzing-1"` with iter=0 — but our new pattern for analyzing is `analyzing-r1`. Update that existing test to match:

```python
    def test_phase_agent_task_for_analyzing(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)
        task = build_phase_task(state, FeatureStatus.analyzing, self._config())
        assert task.feature_id == "feat-x"
        assert task.task_id == "feat-x-analyzing-r1"
        assert task.agent_role == "analyst"
        assert task.input_artifacts == ["artifacts/feat-x/brief.md"]
        assert task.output_artifact == "artifacts/feat-x/spec.r1.md"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: All passing — both `TestBuildPhaseTaskQuestioning` and the updated `test_phase_agent_task_for_analyzing`.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: build_phase_task supports questioning and revision-aware analyzing IDs"
```

---

## Task 16: Create `.agents/product.md`

**Files:**
- Create: `.agents/product.md`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompt_builder.py`:

```python
class TestProductAgentDefinition:
    def test_product_agent_loads_with_correct_frontmatter(self):
        from pathlib import Path
        from agentharness.prompt_builder import load_agent_definition

        agent_def = load_agent_definition(Path(".agents/product.md"))
        assert agent_def.id == "product"
        assert agent_def.model == "claude-opus-4-7"
        assert agent_def.phase == "questioning"
        assert agent_def.allowed_tools == []
        assert agent_def.output_file_glob == "answers.md"
        assert agent_def.visibility_timeout == 300
        assert agent_def.retry_limit == 3
        assert agent_def.max_turns == 1

    def test_product_agent_system_prompt_mentions_open_questions(self):
        from pathlib import Path
        from agentharness.prompt_builder import load_agent_definition

        agent_def = load_agent_definition(Path(".agents/product.md"))
        assert "## Open Questions" in agent_def.system_prompt
        assert "Question" in agent_def.system_prompt
        assert "Rationale" in agent_def.system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_prompt_builder.py::TestProductAgentDefinition -v`
Expected: FAIL — `.agents/product.md` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Create `.agents/product.md`:

```markdown
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

You are a senior product manager and feature owner. Your job is to answer the open questions in a feature spec so the rest of the autonomous pipeline can proceed without ambiguity.

## Your inputs
- `brief.md` — the original feature request
- The latest `spec.r{N}.md` — produced by the analyst, containing a `## Open Questions` section
- Any prior `answers.r{M}.md` files — read in ascending revision order; later answers do not contradict earlier ones, but if they appear to, treat the later answer as authoritative

## Your job

1. Identify the latest `spec.r{N}.md` from your input artifacts (highest revision number).
2. Locate its `## Open Questions` section.
3. For each question, output exactly:

```
### Question {n}
{verbatim question}

**Answer:** {direct, decisive answer — commit to a decision, do not hedge}

**Rationale:** {1–3 sentences explaining the call}
```

4. Write the result to `answers.md` in the work directory root.

## Rules

- Output ONLY the answered-question list. No preamble. No summary. No conclusion.
- If a question cannot be definitively answered, choose the most reasonable default and document the rationale. Leaving any question unanswered is forbidden.
- Do not contradict prior `answers.r{M}.md` files unless authoritatively superseding them — and document the change in the rationale if you do.
- Keep answers concrete: choose a value, name a tool, pick a behavior. The downstream pipeline must be able to act on each answer without further interpretation.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_prompt_builder.py::TestProductAgentDefinition -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add .agents/product.md tests/test_prompt_builder.py
git commit -m "feat: add product agent definition for analyst open-questions loop"
```

---

## Task 17: Register `product-queue` in `.pipeline/config.json`

**Files:**
- Modify: `.pipeline/config.json`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
class TestPipelineConfigJson:
    def test_product_queue_is_registered(self):
        from agentharness.config import load_config
        from pathlib import Path
        cfg = load_config(Path(".pipeline/config.json"))
        assert "product-queue" in cfg.queues
        assert cfg.queues["product-queue"].agent == ".agents/product.md"

    def test_max_analyst_iterations_is_two(self):
        from agentharness.config import load_config
        from pathlib import Path
        cfg = load_config(Path(".pipeline/config.json"))
        assert cfg.max_analyst_iterations == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::TestPipelineConfigJson -v`
Expected: FAIL — neither key is present in the JSON yet.

- [ ] **Step 3: Write minimal implementation**

Edit `.pipeline/config.json`:

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
    "product-queue":   { "agent": ".agents/product.md" },
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py::TestPipelineConfigJson -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add .pipeline/config.json tests/test_config.py
git commit -m "feat: register product-queue and max_analyst_iterations in pipeline config"
```

---

## Task 18: Update analyst agent prompt with status-line contract

**Files:**
- Modify: `.agents/analyst.md`

- [ ] **Step 1: Edit the analyst agent file**

Append the following to `.agents/analyst.md` (after the existing "Output only the specification markdown — no preamble, no explanation." line):

```markdown

## Status line (required)

At the very end of your output, emit exactly one of:

```
## Status: COMPLETE
```

(when `## Open Questions` is empty, absent, or contains only "None.")

or

```
## Status: HAS_QUESTIONS
```

(when `## Open Questions` has at least one question.)

The keyword is case-sensitive. The downstream dispatcher parses this line to decide whether to invoke the product agent before continuing.

## Reading prior answers

When your input artifacts include `answers.r{N}.md` files, read them in ascending revision order (`answers.r1.md` first). For each answer, modify or remove the corresponding question and update any sections it affects. Do not reproduce answered questions in `## Open Questions`. Produce a single, complete, self-contained spec — do not diff against prior revisions.
```

- [ ] **Step 2: Verify the file is well-formed**

Run: `.venv/bin/python -c "from agentharness.prompt_builder import load_agent_definition; from pathlib import Path; print(load_agent_definition(Path('.agents/analyst.md')).id)"`
Expected: prints `analyst`.

- [ ] **Step 3: Commit**

```bash
git add .agents/analyst.md
git commit -m "feat: analyst emits Status line; reads prior answers in order"
```

---

## Task 19: Update TUI to display `questioning` phase and analyst iteration counter

**Files:**
- Modify: `agentharness/tui.py:37-49` (status icons)
- Modify: `agentharness/tui.py:51-57` (status colors)
- Modify: `agentharness/tui.py:59` (phase order)
- Modify: `agentharness/tui.py:61-68` (phase-to-queue map)
- Modify: `agentharness/tui.py:114-124` (`_phase_bar`)
- Modify: `agentharness/tui.py:231-247` (TaskPanel.update_tasks border title)

- [ ] **Step 1: Add `questioning` to status icons, colors, and phase order**

Edit `agentharness/tui.py:37-49`:

```python
_STATUS_ICONS = {
    FeatureStatus.done: "✓",
    FeatureStatus.failed: "✗",
    FeatureStatus.developing: "▶",
    FeatureStatus.reviewing: "▶",
    FeatureStatus.dev_revision: "↺",
    FeatureStatus.analyzing: "◌",
    FeatureStatus.questioning: "◌",
    FeatureStatus.planning: "◌",
    FeatureStatus.architecting: "◌",
    FeatureStatus.designing: "◌",
    FeatureStatus.brainstorming: "◌",
    FeatureStatus.brainstormed: "◎",
}
```

Edit `agentharness/tui.py:51-57`:

```python
_STATUS_COLORS = {
    FeatureStatus.done: "green",
    FeatureStatus.failed: "red",
    FeatureStatus.developing: "yellow",
    FeatureStatus.reviewing: "yellow",
    FeatureStatus.dev_revision: "magenta",
    FeatureStatus.questioning: "cyan",
}
```

Edit `agentharness/tui.py:59`:

```python
_PHASE_ORDER = ["analyzing", "questioning", "architecting", "designing", "planning", "developing", "reviewing"]
```

Edit `agentharness/tui.py:61-68` to include `questioning` in the allowed set:

```python
_PHASE_TO_QUEUE = {
    status.value: queue
    for status, queue in STATE_TO_QUEUE.items()
    if queue is not None and status.value in {
        "analyzing", "questioning", "architecting", "designing",
        "planning", "developing", "reviewing",
    }
}
```

- [ ] **Step 2: Update `_phase_bar` to handle the longer phase list**

Edit `agentharness/tui.py:114-124`:

```python
def _phase_bar(state: FeatureState) -> str:
    total = len(_PHASE_ORDER)
    filled = sum(
        1 for p in _PHASE_ORDER
        if state.phases.get(p) and state.phases[p].status.value == "completed"
    )
    in_progress = any(
        state.phases.get(p) and state.phases[p].status.value == "in_progress"
        for p in _PHASE_ORDER
    )
    bar = "▶" * filled + ("▷" if in_progress else "") + "□" * (total - filled - (1 if in_progress else 0))
    return bar[:total]
```

- [ ] **Step 3: Add analyst-iteration counter to the TaskPanel border title**

Edit `agentharness/tui.py:231-234`:

```python
    def update_tasks(self, state: FeatureState) -> None:
        total = _fmt_tokens(state.total_tokens_used())
        title = f"Tasks  —  total: {total}" if total != "—" else "Tasks"
        cfg = state.config
        if cfg.current_analyst_iteration > 0:
            cap_note = " (cap)" if cfg.current_analyst_iteration >= cfg.max_analyst_iterations else ""
            title = f"{title}  —  analyst: {cfg.current_analyst_iteration} / {cfg.max_analyst_iterations}{cap_note}"
        self.border_title = title
        new_rows, new_ids = self._build_task_rows(state)
        # ... (rest unchanged)
```

- [ ] **Step 4: Smoke-test the TUI module imports cleanly**

Run: `.venv/bin/python -c "from agentharness.tui import _STATUS_ICONS, _PHASE_ORDER; from agentharness.models import FeatureStatus; assert FeatureStatus.questioning in _STATUS_ICONS; assert 'questioning' in _PHASE_ORDER; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add agentharness/tui.py
git commit -m "feat: TUI renders questioning phase and analyst iteration counter"
```

---

## Task 20: Add `questioning` to canonical state order in `tui_state_change.py`

**Files:**
- Modify: `agentharness/tui_state_change.py:22-32`
- Test: `tests/test_tui_state_change.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tui_state_change.py`:

```python
class TestQuestioningInCanonicalOrder:
    def test_questioning_present(self):
        from agentharness.tui_state_change import CANONICAL_STATE_ORDER
        from agentharness.models import FeatureStatus
        assert FeatureStatus.questioning in CANONICAL_STATE_ORDER

    def test_questioning_between_analyzing_and_architecting(self):
        from agentharness.tui_state_change import CANONICAL_STATE_ORDER
        from agentharness.models import FeatureStatus
        order = CANONICAL_STATE_ORDER
        assert order.index(FeatureStatus.analyzing) < order.index(FeatureStatus.questioning)
        assert order.index(FeatureStatus.questioning) < order.index(FeatureStatus.architecting)

    def test_options_for_questioning_state_includes_rollback_to_analyzing(self):
        from agentharness.tui_state_change import StateChangeModal
        from agentharness.models import FeatureState, FeatureStatus
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.questioning)
        options = StateChangeModal._options_for(state)
        statuses = [s for s, _, _ in options]
        assert FeatureStatus.analyzing in statuses
        assert FeatureStatus.questioning in statuses
        assert FeatureStatus.architecting not in statuses  # later state — excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_tui_state_change.py::TestQuestioningInCanonicalOrder -v`
Expected: FAIL — questioning not in canonical order.

- [ ] **Step 3: Write minimal implementation**

Edit `agentharness/tui_state_change.py:22-32`:

```python
CANONICAL_STATE_ORDER: list[FeatureStatus] = [
    FeatureStatus.brainstorming,
    FeatureStatus.brainstormed,
    FeatureStatus.analyzing,
    FeatureStatus.questioning,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
    FeatureStatus.developing,
    FeatureStatus.dev_revision,
    FeatureStatus.reviewing,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tui_state_change.py -v`
Expected: All passing — both new tests and existing ones.

- [ ] **Step 5: Commit**

```bash
git add agentharness/tui_state_change.py tests/test_tui_state_change.py
git commit -m "feat: include questioning in TUI canonical state order"
```

---

## Task 21: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests passing — no regressions in `test_dispatcher.py`, `test_models.py`, `test_config.py`, `test_brainstorm_github.py`, `test_run_task.py`, `test_state_change.py`, `test_tui_state_change.py`, `test_github_state.py`, `test_prompt_builder.py`.

- [ ] **Step 2: Lint with ruff (if installed)**

Run: `.venv/bin/ruff check agentharness/ tests/ || echo "ruff not configured — skipping"`
Expected: clean or skipped.

- [ ] **Step 3: Type-check (if mypy/pyright is configured)**

Run: `.venv/bin/python -m mypy agentharness/ 2>/dev/null || echo "mypy not configured — skipping"`
Expected: clean or skipped.

- [ ] **Step 4: Smoke-test the full happy path with cap=0 (Path D)**

Verify by direct dispatcher unit test that `max_analyst_iterations=0` causes `HAS_QUESTIONS` analyst output to skip the product agent. (Already covered by `test_cap_zero_disables_loop` in Task 14.)

- [ ] **Step 5: Final integration check — config + agent + queue all wired**

Run a one-liner that loads config, ensures product agent is loadable, and the queue→agent path resolves:

```bash
.venv/bin/python -c "
from pathlib import Path
from agentharness.config import load_config
from agentharness.prompt_builder import load_agent_definition

cfg = load_config(Path('.pipeline/config.json'))
assert 'product-queue' in cfg.queues, 'product-queue missing'
assert cfg.max_analyst_iterations == 2, 'cap not set'

product_def = load_agent_definition(cfg.agent_path_for_queue('product-queue'))
assert product_def.id == 'product'
assert product_def.model == 'claude-opus-4-7'
assert product_def.allowed_tools == []
print('product agent loop wired up cleanly')
"
```

Expected: prints `product agent loop wired up cleanly`.

- [ ] **Step 6: Commit any final touch-ups**

If the previous step revealed missing pieces, fix them and commit. Otherwise this task produces no commit.

---

## Self-Review Notes

**Spec coverage:**
- FR-1 (status signal) — Tasks 7, 18 (parser + analyst prompt update)
- FR-2 (conditional dispatch) — Task 14 (dispatch_after_completion branch)
- FR-3 (product agent definition) — Tasks 16, 17 (file + pipeline config)
- FR-4 (analyst re-run with accumulated context) — Tasks 9, 13, 18 (artifact assembly + rerun + prompt)
- FR-5 (cap + counter) — Tasks 2, 5, 6, 13, 14 (model + config propagation + atomic increment + cap check)
- FR-6 (new state and queue) — Tasks 1, 4, 11, 17 (enum + labels + STATE_TO_QUEUE + JSON queue)
- FR-7 (dispatcher changes summary) — Tasks 7-15 (every helper, dispatcher, and signature)
- NFR-1 (transparency) — Task 19 (TUI rendering)
- NFR-2 (cost control) — Tasks 14 (cap check), 17 (default = 2 in JSON)
- NFR-3 (backwards compatibility) — Pydantic defaults in Tasks 2, 5; deserialization tests in Task 2
- NFR-4 (performance) — Task 16 (visibility_timeout=300 in agent frontmatter)
- NFR-5 (idempotency) — Task 13 increments inside the in-memory state then returns it for outer-lease persistence; same task_id pattern across retries

**Architecture review amendments addressed:**
1. `PipelineConfig` not `FeatureStateConfig` — Task 2 ✓
2. `_artifacts_for_phase(state, phase)` signature — Task 9 ✓
3. Latest spec consumption at every `phase_artifact_path(..., 'spec', 1)` site — Tasks 9, 10 ✓
4. Task ID disambiguation — Tasks 12, 13, 15 (`-r{N}` suffix) ✓
5. GitHub label provisioning — Task 4 ✓; runtime auto-creation should already work via existing `github_state.py`/`github_queue.py` label-on-demand behaviour
6. Product agent ascending-revision rule — Task 16 system prompt ✓
7. Worktree behaviour for analyst re-runs — `allowed_tools: []` analyst, no commits — no extra change needed (existing behaviour); confirmed by reading `run_task.py:114` (only commits when `allowed_tools` non-empty)
8. Cap=0 explicit acceptance — Task 14 (`test_cap_zero_disables_loop`) ✓

**Type/method consistency check:** `_latest_spec_revision`, `_parse_analyst_status`, `_dispatch_questioning`, `_dispatch_analyst_rerun`, `with_analyst_iteration_incremented`, `FeatureStatus.questioning`, `FEAT_QUESTIONING`, `QUEUE_PRODUCT`, `product-queue`, `answers.r{N}.md`, `answers.md` (work-dir filename), `max_analyst_iterations`, `current_analyst_iteration` — names appear identically across every task referencing them.

**No placeholders:** every step contains complete code or exact commands.
