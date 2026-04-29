# Raw GitHub Issue TUI Visibility + Auto-Conversion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub issues that carry the configured `feature_marker` label appear in the AgentHarness TUI as `brainstormed` features without manual conversion, and silently convert them into harness-managed features when the user presses `i` (TUI) or runs `agentharness implement`.

**Architecture:** Surgical extension of the GitHub backend slice — three modules touched (`github_state.py`, `brainstorm.py`, `tui.py`) plus a one-line property on `FeatureState`. No new abstractions, no protocol changes, no Azure changes. The synthetic `FeatureState` lives only in memory; the on-disk shape (issue body + labels) is unchanged for raw issues until conversion. A single shared `slug_title()` helper is used for both synthesis and matching to guarantee round-trip equality with `/convertforagent`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest + pytest-asyncio, httpx, Textual TUI, GitHub REST API v3.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `agentharness/models.py` | Modify | Add `FeatureState.is_raw` computed property. |
| `agentharness/github_state.py` | Modify | Add `slug_title()` top-level helper, `_synthesize_raw_state()` helper, `GitHubStateManager.patch_existing_issue()` method; modify `list_features()` to synthesize raw issues instead of skipping them. |
| `agentharness/brainstorm.py` | Modify | Refactor `_slug_from_brief()` to delegate to `slug_title()`; add private `_convert_raw_issue()`; modify `enqueue_planner()` with GitHub-only pre-flight conversion. |
| `agentharness/tui.py` | Modify | Add `is_raw` early-return guard in `action_open_state_change`. |
| `tests/test_models.py` | Modify | Test `FeatureState.is_raw`. |
| `tests/test_github_state.py` | Modify | Tests for `slug_title`, `_synthesize_raw_state`, `list_features` synthesis path, `patch_existing_issue` (idempotent / append / replace / label add). |
| `tests/test_brainstorm_github.py` | Modify | Tests for `_convert_raw_issue` (happy path, missing-issue, branch-exists) and `enqueue_planner` GitHub pre-flight (raw → convert; initialized → skip; Azure unchanged). |
| `tests/test_tui_state_change.py` | Modify | Test that the TUI's `action_open_state_change` guard fires for raw features. |

No new files. `slug_title` lives in `github_state.py` (top-level function) — it is the only non-brainstorm consumer in the codebase, and placing it next to `_synthesize_raw_state` keeps the round-trip contract obvious to future readers.

---

## Task 1: `FeatureState.is_raw` computed property

**Files:**
- Modify: `agentharness/models.py:102-203`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
from agentharness.models import FeatureState, FeatureStatus, HistoryEvent


class TestFeatureStateIsRaw:
    def test_is_raw_true_for_empty_history(self):
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.brainstormed)
        assert state.is_raw is True

    def test_is_raw_false_after_brief_uploaded_event(self):
        state = FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.brainstormed,
        ).with_event("brief_uploaded")
        assert state.is_raw is False

    def test_is_raw_is_not_persisted_in_serialised_form(self):
        """Computed properties must not appear in model_dump output."""
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.brainstormed)
        dumped = state.model_dump()
        assert "is_raw" not in dumped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py::TestFeatureStateIsRaw -v`
Expected: FAIL — `AttributeError: 'FeatureState' object has no attribute 'is_raw'` on the first two; the third may pass trivially.

- [ ] **Step 3: Implement the property**

In `agentharness/models.py`, locate the `FeatureState` class. After the `total_tokens_used` method (around line 187, before `tasks_for_phase`), add:

```python
    @property
    def is_raw(self) -> bool:
        """True when this state was synthesised from a labelled issue with no state block.

        A raw feature has no recorded history events; the canonical signal is the
        absence of the `brief_uploaded` event that ``upload_brief`` emits. Only
        meaningful for ``FeatureState`` objects produced by ``list_features()`` or
        synthesised locally; do not trust after a write round-trip via ``get()``.
        """
        return not self.history
```

Pydantic v2 already excludes computed `@property` from `model_dump`, so no extra config is required.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py::TestFeatureStateIsRaw -v`
Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_models.py
git commit -m "feat: add FeatureState.is_raw property for raw-feature detection"
```

---

## Task 2: Shared `slug_title` helper + refactor `_slug_from_brief`

**Files:**
- Modify: `agentharness/github_state.py:30-40` (add helper after the regex constants)
- Modify: `agentharness/brainstorm.py:29-37` (refactor)
- Test: `tests/test_github_state.py` (new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_state.py` after the existing helper tests (around the `# create` section header — anywhere top-level is fine):

```python
# ---------------------------------------------------------------------------
# slug_title
# ---------------------------------------------------------------------------


class TestSlugTitle:
    """The slug algorithm must match /convertforagent byte-for-byte.

    Reference: .claude/skills/convertforagent/SKILL.md, slug() definition.
    """

    def test_lowercases_and_replaces_non_alnum_with_dash(self):
        from agentharness.github_state import slug_title
        assert slug_title("My Feature!") == "my-feature"

    def test_strips_leading_and_trailing_dashes(self):
        from agentharness.github_state import slug_title
        assert slug_title("  Hello  ") == "hello"
        assert slug_title("---X---") == "x"

    def test_collapses_consecutive_separators(self):
        from agentharness.github_state import slug_title
        assert slug_title("foo   bar___baz") == "foo-bar-baz"

    def test_truncates_to_40_chars(self):
        from agentharness.github_state import slug_title
        title = "a" * 60
        result = slug_title(title)
        assert len(result) == 40
        assert result == "a" * 40

    def test_preserves_digits(self):
        from agentharness.github_state import slug_title
        assert slug_title("Add v2 Endpoint") == "add-v2-endpoint"

    def test_strips_unicode_to_dashes(self):
        from agentharness.github_state import slug_title
        assert slug_title("café résumé") == "caf-r-sum"
```

Then append a brainstorm-side delegation test to `tests/test_brainstorm_github.py`:

```python
# ---------------------------------------------------------------------------
# _slug_from_brief delegation
# ---------------------------------------------------------------------------


class TestSlugFromBriefDelegates:
    def test_brief_h1_passed_through_slug_title(self):
        from agentharness.brainstorm import _slug_from_brief
        # Same algorithm as slug_title after stripping the optional prefix
        assert _slug_from_brief("# Feature Brief: My Cool Thing\n\nbody") == "my-cool-thing"

    def test_no_h1_yields_untitled(self):
        from agentharness.brainstorm import _slug_from_brief
        assert _slug_from_brief("body without heading") == "untitled"

    def test_round_trip_with_slug_title(self):
        """If the H1 line lacks a 'Feature Brief:' prefix, _slug_from_brief must
        equal slug_title applied to the raw heading text."""
        from agentharness.brainstorm import _slug_from_brief
        from agentharness.github_state import slug_title
        assert _slug_from_brief("# Add User Export Endpoint\n") == slug_title("Add User Export Endpoint")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_state.py::TestSlugTitle tests/test_brainstorm_github.py::TestSlugFromBriefDelegates -v`
Expected: FAIL — `ImportError: cannot import name 'slug_title'` for the github_state tests; the brainstorm round-trip test fails for the same reason.

- [ ] **Step 3: Add `slug_title` to `github_state.py`**

In `agentharness/github_state.py`, immediately after the `_STATE_BLOCK_RE` definition (around line 38, before `# Helpers` comment), add:

```python
# ---------------------------------------------------------------------------
# Slug helper — single source of truth shared between synthesis and matching.
#
# Algorithm contract (must match the /convertforagent skill byte-for-byte):
#   1. lowercase
#   2. replace runs of non-[a-z0-9] with a single "-"
#   3. strip leading/trailing "-"
#   4. truncate to 40 characters
#
# Any change here affects feature_id derivation across the entire pipeline.
# ---------------------------------------------------------------------------


def slug_title(title: str) -> str:
    """Return a 40-char URL-safe slug of *title* (matches /convertforagent)."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40]
```

- [ ] **Step 4: Refactor `_slug_from_brief` in `brainstorm.py`**

Replace the existing `_slug_from_brief` function (currently `agentharness/brainstorm.py:29-37`):

```python
def _slug_from_brief(brief_content: str) -> str:
    """Extract the H1 line from *brief_content* and slug it via slug_title."""
    import re
    from agentharness.github_state import slug_title

    for line in brief_content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = re.sub(r"^#\s*(Feature Brief:\s*)?", "", line, flags=re.IGNORECASE)
            return slug_title(title)
    return "untitled"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py::TestSlugTitle tests/test_brainstorm_github.py::TestSlugFromBriefDelegates -v`
Expected: PASS for all 9 tests.

Also re-run the full brainstorm suite to confirm we didn't regress:

Run: `.venv/bin/pytest tests/test_brainstorm_github.py tests/test_brainstorm_pipeline_config.py -v`
Expected: All previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add agentharness/github_state.py agentharness/brainstorm.py tests/test_github_state.py tests/test_brainstorm_github.py
git commit -m "refactor: extract slug_title helper shared by synth and brainstorm"
```

---

## Task 3: `_synthesize_raw_state` helper

**Files:**
- Modify: `agentharness/github_state.py` (add private helper before the `GitHubStateManager` class)
- Test: `tests/test_github_state.py` (new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_state.py` (top-level, after the `slug_title` tests):

```python
# ---------------------------------------------------------------------------
# _synthesize_raw_state
# ---------------------------------------------------------------------------


class TestSynthesizeRawState:
    def _raw_issue(
        self,
        *,
        number: int = 7,
        title: str = "Add User Export Endpoint",
        body: str = "Original description",
        created_at: str = "2026-04-25T10:00:00Z",
        updated_at: str = "2026-04-26T11:00:00Z",
    ) -> dict:
        return {
            "number": number,
            "title": title,
            "body": body,
            "created_at": created_at,
            "updated_at": updated_at,
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }

    def test_feature_id_uses_slug_title_with_feat_prefix(self):
        from agentharness.github_state import _synthesize_raw_state, slug_title
        state = _synthesize_raw_state(self._raw_issue(title="Add User Export Endpoint"))
        assert state.feature_id == f"feat-{slug_title('Add User Export Endpoint')}"
        assert state.feature_id == "feat-add-user-export-endpoint"

    def test_status_is_brainstormed(self):
        from agentharness.github_state import _synthesize_raw_state
        from agentharness.models import FeatureStatus
        state = _synthesize_raw_state(self._raw_issue())
        assert state.status == FeatureStatus.brainstormed

    def test_state_issue_number_set(self):
        from agentharness.github_state import _synthesize_raw_state
        state = _synthesize_raw_state(self._raw_issue(number=42))
        assert state.state_issue_number == 42

    def test_branch_name_equals_feature_id(self):
        from agentharness.github_state import _synthesize_raw_state
        state = _synthesize_raw_state(self._raw_issue(title="Cool Thing"))
        assert state.branch_name == state.feature_id == "feat-cool-thing"

    def test_history_phases_tasks_are_empty(self):
        from agentharness.github_state import _synthesize_raw_state
        state = _synthesize_raw_state(self._raw_issue())
        assert state.history == []
        assert state.phases == {}
        assert state.tasks == []

    def test_is_raw_property_true_for_synthesized(self):
        from agentharness.github_state import _synthesize_raw_state
        state = _synthesize_raw_state(self._raw_issue())
        assert state.is_raw is True

    def test_timestamps_taken_from_issue(self):
        from datetime import datetime, timezone
        from agentharness.github_state import _synthesize_raw_state
        state = _synthesize_raw_state(
            self._raw_issue(
                created_at="2026-04-25T10:00:00Z",
                updated_at="2026-04-26T11:00:00Z",
            )
        )
        assert state.created_at == datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        assert state.updated_at == datetime(2026, 4, 26, 11, 0, 0, tzinfo=timezone.utc)

    def test_handles_missing_timestamps_gracefully(self):
        """Issue dicts truncated by list_issues may lack created_at/updated_at."""
        from agentharness.github_state import _synthesize_raw_state
        issue = self._raw_issue()
        issue.pop("created_at")
        issue.pop("updated_at")
        # Should not raise; falls back to model defaults (datetime.utcnow at construction)
        state = _synthesize_raw_state(issue)
        assert state.created_at is not None
        assert state.updated_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_state.py::TestSynthesizeRawState -v`
Expected: FAIL — `ImportError: cannot import name '_synthesize_raw_state'`.

- [ ] **Step 3: Implement `_synthesize_raw_state`**

In `agentharness/github_state.py`, add the helper directly above the `# GitHubStateManager` section header (around line 116):

```python
def _parse_iso_timestamp(value: str | None) -> "datetime | None":
    """Parse a GitHub ISO-8601 timestamp into a UTC datetime, or None."""
    from datetime import datetime, timezone
    if not value:
        return None
    # GitHub returns "2026-04-25T10:00:00Z"; fromisoformat needs +00:00 in <3.11.
    cleaned = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _synthesize_raw_state(issue: dict) -> FeatureState:
    """Build a synthetic FeatureState for a labelled issue without a state block.

    Used by ``GitHubStateManager.list_features`` to surface raw issues in the TUI.
    The resulting state has ``is_raw is True`` (empty history) — that flag is the
    canonical signal that the issue still needs ``_convert_raw_issue`` before it
    can transition out of ``brainstormed``.
    """
    title = issue.get("title") or ""
    feature_id = f"feat-{slug_title(title)}"

    fields: dict = {
        "feature_id": feature_id,
        "status": FeatureStatus.brainstormed,
        "state_issue_number": int(issue["number"]),
        "branch_name": feature_id,
    }
    created_at = _parse_iso_timestamp(issue.get("created_at"))
    if created_at is not None:
        fields["created_at"] = created_at
    updated_at = _parse_iso_timestamp(issue.get("updated_at"))
    if updated_at is not None:
        fields["updated_at"] = updated_at

    return FeatureState(**fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py::TestSynthesizeRawState -v`
Expected: PASS for all 8 tests.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_state.py tests/test_github_state.py
git commit -m "feat: add _synthesize_raw_state for surfacing raw labelled issues"
```

---

## Task 4: `list_features` synthesises raw issues instead of skipping

**Files:**
- Modify: `agentharness/github_state.py:286-323` (`list_features` method)
- Test: `tests/test_github_state.py` (new test cases)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_github_state.py` in the `# list_features` section (replace `test_list_features_skips_issues_without_parseable_state` since the contract is now to surface, not skip — keep the name but invert the assertion):

```python
# ---------------------------------------------------------------------------
# list_features — raw-issue synthesis
# ---------------------------------------------------------------------------


def _make_raw_issue(
    *,
    number: int,
    title: str = "Raw Feature Title",
    body: str = "Raw issue body",
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "created_at": "2026-04-25T10:00:00Z",
        "updated_at": "2026-04-25T10:00:00Z",
        "labels": [{"name": TEST_FEATURE_MARKER}],
    }


@pytest.mark.asyncio
async def test_list_features_synthesizes_raw_issue_without_state_block():
    """An issue with the marker label but no state JSON now appears as raw."""
    raw = _make_raw_issue(number=11, title="Add Export Endpoint")
    client = _mock_client()
    client.list_issues.return_value = [raw]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    results = await mgr.list_features()

    assert len(results) == 1
    state = results[0]
    assert state.feature_id == "feat-add-export-endpoint"
    assert state.status == FeatureStatus.brainstormed
    assert state.state_issue_number == 11
    assert state.branch_name == "feat-add-export-endpoint"
    assert state.is_raw is True


@pytest.mark.asyncio
async def test_list_features_returns_both_raw_and_initialized_features():
    initialized_state = _make_state("feat-initialized")
    initialized = _make_issue(initialized_state, number=20)
    raw = _make_raw_issue(number=21, title="Raw Thing")
    client = _mock_client()
    client.list_issues.return_value = [raw, initialized]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    results = await mgr.list_features()

    feature_ids = {s.feature_id for s in results}
    assert feature_ids == {"feat-initialized", "feat-raw-thing"}
    raw_state = next(s for s in results if s.feature_id == "feat-raw-thing")
    init_state = next(s for s in results if s.feature_id == "feat-initialized")
    assert raw_state.is_raw is True
    assert init_state.is_raw is False


@pytest.mark.asyncio
async def test_list_features_dedup_two_raw_issues_keeps_newest():
    """When two raw issues slug to the same feature_id, the higher number wins."""
    older = _make_raw_issue(number=1, title="Same Title")
    newer = _make_raw_issue(number=5, title="Same Title")
    client = _mock_client()
    client.list_issues.return_value = [newer, older]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    results = await mgr.list_features()

    assert len(results) == 1
    assert results[0].state_issue_number == 5


@pytest.mark.asyncio
async def test_list_features_dedup_raw_vs_initialized_keeps_newest():
    """Raw and initialized issues with the same slug → newest wins per existing rule."""
    initialized_state = _make_state("feat-shared-slug")
    initialized = _make_issue(initialized_state, number=2)
    raw = _make_raw_issue(number=8, title="Shared Slug")  # slugs to feat-shared-slug
    client = _mock_client()
    client.list_issues.return_value = [raw, initialized]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    results = await mgr.list_features()

    assert len(results) == 1
    # raw issue 8 is newer than initialized issue 2 → raw wins
    assert results[0].state_issue_number == 8
    assert results[0].is_raw is True


@pytest.mark.asyncio
async def test_list_features_returns_empty_when_no_issues():
    """Already exists in test file; confirm still passes after refactor."""
    client = _mock_client()
    client.list_issues.return_value = []
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    results = await mgr.list_features()

    assert results == []
```

Also **delete** the old `test_list_features_skips_issues_without_parseable_state` test (around `tests/test_github_state.py:434-453`) — its contract is being replaced. The new behaviour is "synthesize, don't skip".

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_state.py -k "list_features" -v`
Expected: FAIL on `test_list_features_synthesizes_raw_issue_without_state_block`, `test_list_features_returns_both_raw_and_initialized_features`, `test_list_features_dedup_two_raw_issues_keeps_newest`, `test_list_features_dedup_raw_vs_initialized_keeps_newest` — these all rely on the synthesis fallback. The current code still skips them and returns 0 results.

- [ ] **Step 3: Modify `list_features` to synthesise**

In `agentharness/github_state.py`, replace the body of `list_features` (currently lines 286-323) with:

```python
    async def list_features(self) -> list[FeatureState]:
        """Return all known features as parsed FeatureState objects.

        Issues that carry the ``feature_marker`` label but do not embed an
        ``agentharness-state`` JSON block are surfaced as *synthetic* raw states
        (``status=brainstormed``, ``history=[]``). They are not persisted in
        synthetic form — the next ``patch_existing_issue`` call writes the real
        state block. ``state.is_raw`` distinguishes raw from initialised states.

        Results are sorted by issue number descending (newest first). When the
        same ``feature_id`` appears in multiple issues, only the highest-numbered
        issue is kept (raw + initialised dedup using the same rule).
        """
        items = await self._client.list_issues(labels=[self._feature_marker], direction="desc")

        # feature_id -> (issue_number, issue_dict, parsed_state_or_None) — newest wins
        seen: dict[str, tuple[int, dict, FeatureState | None]] = {}
        for issue in items:
            issue_number: int = int(issue["number"])
            parsed = self._parse_state_from_issue(issue)
            if parsed is not None:
                feature_id = parsed.feature_id
            else:
                title = issue.get("title") or ""
                feature_id = f"feat-{slug_title(title)}"
            existing = seen.get(feature_id)
            if existing is None or issue_number > existing[0]:
                seen[feature_id] = (issue_number, issue, parsed)

        sorted_triples = sorted(seen.values(), key=lambda t: t[0], reverse=True)

        states: list[FeatureState] = []
        for _issue_number, issue, parsed in sorted_triples:
            if parsed is None:
                states.append(_synthesize_raw_state(issue))
                continue
            try:
                state = await self._state_from_issue(issue)
                states.append(state)
            except Exception:
                log.debug(
                    "Could not reconstruct state for issue #%d — synthesising as raw",
                    issue["number"],
                )
                states.append(_synthesize_raw_state(issue))
        return states
```

Note: the previous per-issue `log.warning("...no parseable state JSON — skipping")` is removed entirely. Synthesis is the new normal — logging it on every TUI refresh would be noise. The fallback inside the `try` block is downgraded to `log.debug` since recovery is automatic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py -k "list_features" -v`
Expected: PASS for all 5 tests.

Also re-run the full module to confirm no regressions:

Run: `.venv/bin/pytest tests/test_github_state.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_state.py tests/test_github_state.py
git commit -m "feat: synthesise raw issues in list_features instead of skipping"
```

---

## Task 5: `GitHubStateManager.patch_existing_issue` method

**Files:**
- Modify: `agentharness/github_state.py` (add public method on `GitHubStateManager`)
- Test: `tests/test_github_state.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_github_state.py`:

```python
# ---------------------------------------------------------------------------
# patch_existing_issue
# ---------------------------------------------------------------------------


class TestPatchExistingIssue:
    @pytest.mark.asyncio
    async def test_appends_state_block_when_absent(self):
        from agentharness.github_state import _STATE_BLOCK_RE, parse_state_from_issue
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
        # Existing issue has no state block — just a brief description
        client.get_issue.return_value = {
            "number": 5,
            "body": "Original brief content here.",
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, state, brief_content="Original brief content here.")

        client.update_issue.assert_awaited_once()
        call_kwargs = client.update_issue.call_args[1]
        new_body = call_kwargs["body"]
        assert "Original brief content here." in new_body
        assert _STATE_BLOCK_RE.search(new_body) is not None
        parsed = parse_state_from_issue({"body": new_body})
        assert parsed is not None
        assert parsed.feature_id == "feat-x"

    @pytest.mark.asyncio
    async def test_replaces_existing_state_block(self):
        from agentharness.github_state import _build_state_block, parse_state_from_issue
        old_state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        new_state = _make_state("feat-x", status=FeatureStatus.analyzing)
        old_body = f"Brief content.\n\n{_build_state_block(old_state)}"
        client = _mock_client()
        client.get_issue.return_value = {
            "number": 5,
            "body": old_body,
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, new_state)

        new_body = client.update_issue.call_args[1]["body"]
        assert new_body.count("```agentharness-state") == 1
        parsed = parse_state_from_issue({"body": new_body})
        assert parsed is not None
        assert parsed.status == FeatureStatus.analyzing

    @pytest.mark.asyncio
    async def test_adds_feat_brainstormed_label(self):
        from agentharness.github_labels import FEAT_BRAINSTORMED
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
        client.get_issue.return_value = {
            "number": 5,
            "body": "",
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, state)

        client.ensure_labels.assert_awaited_once()
        names_arg = client.ensure_labels.call_args[0][0]
        assert FEAT_BRAINSTORMED in names_arg
        client.add_labels.assert_awaited_once_with(5, [FEAT_BRAINSTORMED])

    @pytest.mark.asyncio
    async def test_does_not_remove_feature_marker_label(self):
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
        client.get_issue.return_value = {
            "number": 5,
            "body": "",
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, state)

        client.remove_label.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idempotent_two_calls_yield_same_body(self):
        """Two consecutive calls with the same state produce byte-identical bodies."""
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
        # First call: no state block
        first_body_holder = {"body": "Some brief text."}

        async def get_issue_stub(_n: int) -> dict:
            return {"number": 5, "body": first_body_holder["body"], "labels": [{"name": TEST_FEATURE_MARKER}]}

        async def update_issue_stub(_n: int, *, body: str) -> dict:
            first_body_holder["body"] = body
            return {"number": 5}

        client.get_issue.side_effect = get_issue_stub
        client.update_issue.side_effect = update_issue_stub
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, state, brief_content="Some brief text.")
        body_after_first = first_body_holder["body"]

        await mgr.patch_existing_issue(5, state, brief_content="Some brief text.")
        body_after_second = first_body_holder["body"]

        assert body_after_first == body_after_second

    @pytest.mark.asyncio
    async def test_brief_content_preserved_when_already_in_body(self):
        """If the existing body already contains the brief, patch must not duplicate it."""
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
        client.get_issue.return_value = {
            "number": 5,
            "body": "My brief content.",
            "labels": [{"name": TEST_FEATURE_MARKER}],
        }
        mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

        await mgr.patch_existing_issue(5, state, brief_content="My brief content.")

        new_body = client.update_issue.call_args[1]["body"]
        # "My brief content." should appear exactly once
        assert new_body.count("My brief content.") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_state.py::TestPatchExistingIssue -v`
Expected: FAIL — `AttributeError: 'GitHubStateManager' object has no attribute 'patch_existing_issue'`.

- [ ] **Step 3: Implement `patch_existing_issue`**

In `agentharness/github_state.py`, add the new method to `GitHubStateManager`. Place it directly after the `create` method (around line 228), before `get`:

```python
    async def patch_existing_issue(
        self,
        issue_number: int,
        state: FeatureState,
        brief_content: str = "",
    ) -> None:
        """Embed harness state into an *existing* GitHub issue (no issue creation).

        Side effects:
          1. Ensure ``feature_marker`` and ``feat:brainstormed`` labels exist in
             the repo (idempotent).
          2. Add ``feat:brainstormed`` to the target issue. The original
             ``feature_marker`` label is left untouched.
          3. PATCH the issue body to carry an ``agentharness-state`` block —
             appending if absent, replacing if present.

        Idempotent: re-calling with the same *state* yields a byte-identical body
        (the JSON block uses ``model_dump_json`` and re-serialising the same model
        produces stable output).
        """
        from agentharness.github_labels import FEAT_BRAINSTORMED

        await self._client.ensure_labels(
            [self._feature_marker, FEAT_BRAINSTORMED],
            color="0075ca",
        )
        await self._client.add_labels(issue_number, [FEAT_BRAINSTORMED])

        issue = await self._client.get_issue(issue_number)
        existing_body = issue.get("body") or ""

        # If the brief is provided and is not already in the body, prepend it.
        # This matches /convertforagent semantics: the body becomes the brief
        # plus the trailing state block.
        if brief_content and brief_content not in existing_body:
            base_body = (
                f"{existing_body}\n\n{brief_content}".strip()
                if existing_body.strip()
                else brief_content
            )
        else:
            base_body = existing_body

        new_body = _replace_state_block(base_body, state)
        await self._client.update_issue(issue_number, body=new_body)

        log.info(
            "Patched existing issue #%d with state for feature %s",
            issue_number,
            state.feature_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py::TestPatchExistingIssue -v`
Expected: PASS for all 6 tests.

Also re-run the full module:

Run: `.venv/bin/pytest tests/test_github_state.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_state.py tests/test_github_state.py
git commit -m "feat: add GitHubStateManager.patch_existing_issue for raw-issue conversion"
```

---

## Task 6: `_convert_raw_issue` helper in `brainstorm.py`

**Files:**
- Modify: `agentharness/brainstorm.py` (add private async function, after `_fetch_brief_for_feature`)
- Test: `tests/test_brainstorm_github.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_brainstorm_github.py`:

```python
# ---------------------------------------------------------------------------
# _convert_raw_issue
# ---------------------------------------------------------------------------


class TestConvertRawIssue:
    @staticmethod
    def _raw_issue(*, number: int = 7, title: str, body: str = "Issue body content.") -> dict:
        return {
            "number": number,
            "title": title,
            "body": body,
            "created_at": "2026-04-25T10:00:00Z",
            "updated_at": "2026-04-25T10:00:00Z",
            "labels": [{"name": "agent"}],
        }

    @pytest.mark.asyncio
    async def test_happy_path_creates_branch_uploads_brief_patches_issue(self):
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        config.github.feature_marker = "agent"

        # Mock GitHubClient (used to list issues + create branch)
        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Add Export Endpoint")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref = AsyncMock(return_value={"ref": "refs/heads/feat-add-export-endpoint"})
        gh_client.close = AsyncMock()

        store = _make_store(work_dir="/clone/feat-add-export-endpoint")
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            await _convert_raw_issue("feat-add-export-endpoint", config)

        # Branch creation
        gh_client.create_ref.assert_awaited_once()
        ref_args = gh_client.create_ref.call_args
        assert ref_args.args[0] == "refs/heads/feat-add-export-endpoint"
        assert ref_args.args[1] == "abc123"

        # Brief artifact upload
        store.upload.assert_awaited_once_with(
            "artifacts/feat-add-export-endpoint/brief.md",
            "Issue body content.",
        )

        # Issue patch
        state_mgr.patch_existing_issue.assert_awaited_once()
        call_args = state_mgr.patch_existing_issue.call_args
        assert call_args.args[0] == 7  # issue number
        patched_state = call_args.args[1]
        assert patched_state.feature_id == "feat-add-export-endpoint"
        assert patched_state.status == FeatureStatus.brainstormed
        assert patched_state.state_issue_number == 7
        assert patched_state.branch_name == "feat-add-export-endpoint"
        assert call_args.kwargs.get("brief_content") == "Issue body content."

    @pytest.mark.asyncio
    async def test_branch_already_exists_is_tolerated(self):
        """A 422 on create_ref means the branch exists; conversion still completes."""
        from agentharness.brainstorm import _convert_raw_issue
        from agentharness.github_client import GitHubApiError

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Already Exists")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref.side_effect = GitHubApiError(422, "Reference already exists")
        gh_client.close = AsyncMock()

        store = _make_store(work_dir="/clone/feat-already-exists")
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            # Must not raise
            await _convert_raw_issue("feat-already-exists", config)

        # Subsequent steps still run
        store.upload.assert_awaited_once()
        state_mgr.patch_existing_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_matching_issue_raises_value_error(self):
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Different Title")
        ]
        gh_client.close = AsyncMock()

        with patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client):
            with pytest.raises(ValueError, match="feat-no-such-feature"):
                await _convert_raw_issue("feat-no-such-feature", config)

    @pytest.mark.asyncio
    async def test_closes_resources_even_on_error(self):
        """If patch_existing_issue raises, we still close client/store/state_mgr."""
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Boom Title")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref = AsyncMock(return_value={})
        gh_client.close = AsyncMock()

        store = _make_store()
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock(side_effect=RuntimeError("api down"))
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            with pytest.raises(RuntimeError, match="api down"):
                await _convert_raw_issue("feat-boom-title", config)

        gh_client.close.assert_awaited_once()
        store.close.assert_awaited_once()
        state_mgr.close.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brainstorm_github.py::TestConvertRawIssue -v`
Expected: FAIL — `ImportError: cannot import name '_convert_raw_issue'`.

- [ ] **Step 3: Implement `_convert_raw_issue`**

In `agentharness/brainstorm.py`, add the helper at the end of the file (after `_fetch_brief_for_feature`, before `upload_brief_file`):

```python
async def _convert_raw_issue(feature_id: str, config: Config) -> None:
    """Convert a labelled-but-not-initialised GitHub issue into a harness feature.

    Performs the in-Python equivalent of the ``/convertforagent`` skill:
      1. Find the open issue whose title slug matches *feature_id*.
      2. Create the feature branch (idempotent; existing branch is tolerated).
      3. Upload the issue body as ``artifacts/{feature_id}/brief.md``.
      4. Patch the issue with labels + state JSON block.

    Idempotent on retry: branch creation is 422-tolerant, artifact upload
    overwrites any existing ``brief.md``, and ``patch_existing_issue`` replaces
    the state block in place. Raises ``ValueError`` if no open issue matches.
    """
    from agentharness.github_client import GitHubApiError, GitHubClient
    from agentharness.github_state import slug_title

    expected_slug = feature_id.removeprefix("feat-")

    gh_client = GitHubClient.from_config(config)
    store = create_artifact_store(config, feature_id=feature_id)
    state_mgr = create_state_manager(config)
    try:
        # 1. Find the matching issue
        issues = await gh_client.list_issues(labels=[config.github.feature_marker])
        match: dict | None = None
        for issue in issues:
            title = issue.get("title") or ""
            if slug_title(title) == expected_slug:
                match = issue
                break
        if match is None:
            raise ValueError(
                f"no raw issue found for {feature_id!r} "
                f"(no open issue with label {config.github.feature_marker!r} "
                f"slugs to {expected_slug!r})"
            )
        issue_number = int(match["number"])
        brief_content = match.get("body") or ""

        # 2. Create branch (tolerate 'already exists')
        default_branch = await gh_client.get_default_branch()
        ref = await gh_client.get_ref(f"heads/{default_branch}")
        sha = ref["object"]["sha"]
        try:
            await gh_client.create_ref(f"refs/heads/{feature_id}", sha)
            log.info("Created feature branch %s", feature_id)
        except GitHubApiError as exc:
            if exc.status_code == 422:
                log.info("Feature branch %s already exists — skipping creation", feature_id)
            else:
                raise

        # 3. Upload brief
        from agentharness.storage import artifact_path
        await store.upload(artifact_path(feature_id, "brief.md"), brief_content)

        # 4. Build state and patch the issue
        state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.brainstormed,
            state_issue_number=issue_number,
            branch_name=feature_id,
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
                max_analyst_iterations=config.max_analyst_iterations,
            ),
        ).with_event("brief_uploaded")
        await state_mgr.patch_existing_issue(issue_number, state, brief_content=brief_content)
        log.info("Auto-converted raw issue #%d → feature %s", issue_number, feature_id)
    finally:
        await gh_client.close()
        await store.close()
        await state_mgr.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brainstorm_github.py::TestConvertRawIssue -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add agentharness/brainstorm.py tests/test_brainstorm_github.py
git commit -m "feat: add _convert_raw_issue helper for in-Python issue conversion"
```

---

## Task 7: `enqueue_planner` GitHub pre-flight conversion

**Files:**
- Modify: `agentharness/brainstorm.py:175-232` (`enqueue_planner` function)
- Test: `tests/test_brainstorm_github.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_brainstorm_github.py`:

```python
# ---------------------------------------------------------------------------
# enqueue_planner — GitHub raw-issue pre-flight
# ---------------------------------------------------------------------------


class TestEnqueuePlannerPreflight:
    @pytest.mark.asyncio
    async def test_github_raw_feature_triggers_conversion_then_enqueues(self):
        """When state_mgr.get raises KeyError on GitHub, _convert_raw_issue runs first."""
        import tempfile

        config = _make_config(storage_backend="github")
        config.github.feature_marker = "agent"

        queue = _make_queue()
        state_mgr = _make_state_mgr()
        # First .get() (preflight) raises; subsequent ops succeed
        state_mgr.get = AsyncMock(side_effect=KeyError("not found"))

        convert = AsyncMock()

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(work_dir=tmp)
            with (
                patch("agentharness.brainstorm.create_task_queue", return_value=queue),
                patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
                patch("agentharness.brainstorm.create_artifact_store", return_value=store),
                patch(
                    "agentharness.brainstorm._fetch_brief_for_feature",
                    new=AsyncMock(return_value=_BRIEF_CONTENT),
                ),
                patch("agentharness.brainstorm._convert_raw_issue", new=convert),
            ):
                await enqueue_planner(_FEATURE_ID, config)

        # Pre-flight ran exactly once, with the right args
        convert.assert_awaited_once_with(_FEATURE_ID, config)
        # Existing enqueue path still ran (analyst task sent)
        queue.send_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_github_initialized_feature_skips_conversion(self):
        """When state_mgr.get succeeds, _convert_raw_issue is NOT called."""
        import tempfile

        config = _make_config(storage_backend="github")
        config.github.feature_marker = "agent"

        queue = _make_queue()
        state_mgr = _make_state_mgr()
        # Pre-flight .get() succeeds — feature is already initialised
        from agentharness.models import FeatureState, FeatureStatus
        state_mgr.get = AsyncMock(
            return_value=FeatureState(feature_id=_FEATURE_ID, status=FeatureStatus.brainstormed)
        )

        convert = AsyncMock()

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(work_dir=tmp)
            with (
                patch("agentharness.brainstorm.create_task_queue", return_value=queue),
                patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
                patch("agentharness.brainstorm.create_artifact_store", return_value=store),
                patch(
                    "agentharness.brainstorm._fetch_brief_for_feature",
                    new=AsyncMock(return_value=_BRIEF_CONTENT),
                ),
                patch("agentharness.brainstorm._convert_raw_issue", new=convert),
            ):
                await enqueue_planner(_FEATURE_ID, config)

        convert.assert_not_awaited()
        queue.send_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_azure_backend_does_not_run_preflight(self):
        """Azure path must not invoke _convert_raw_issue or call state_mgr.get."""
        config = _make_config(storage_backend="azure")
        queue = _make_queue()
        state_mgr = _make_state_mgr()
        state_mgr.get = AsyncMock()  # would fail if called (no return_value)

        convert = AsyncMock()

        with (
            patch("agentharness.brainstorm.create_task_queue", return_value=queue),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm._convert_raw_issue", new=convert),
        ):
            await enqueue_planner(_FEATURE_ID, config)

        convert.assert_not_awaited()
        state_mgr.get.assert_not_awaited()
        queue.send_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_value_error_from_convert_propagates_to_caller(self):
        """ValueError ('no raw issue found') must propagate (TUI surfaces it)."""
        config = _make_config(storage_backend="github")
        config.github.feature_marker = "agent"

        queue = _make_queue()
        state_mgr = _make_state_mgr()
        state_mgr.get = AsyncMock(side_effect=KeyError("not found"))

        convert = AsyncMock(side_effect=ValueError("no raw issue found for 'feat-x'"))

        with (
            patch("agentharness.brainstorm.create_task_queue", return_value=queue),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm._convert_raw_issue", new=convert),
        ):
            with pytest.raises(ValueError, match="no raw issue found"):
                await enqueue_planner(_FEATURE_ID, config)

        # Conversion ran, propagation succeeded, no task was queued
        convert.assert_awaited_once()
        queue.send_task.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brainstorm_github.py::TestEnqueuePlannerPreflight -v`
Expected: FAIL — the pre-flight branch does not exist yet, so `_convert_raw_issue` is never called.

- [ ] **Step 3: Modify `enqueue_planner` to add the pre-flight**

In `agentharness/brainstorm.py`, locate `enqueue_planner` (line 175). Replace its body so the pre-flight runs **before** the existing `state_mgr.update(...)` call:

```python
async def enqueue_planner(feature_id: str, config: Config) -> None:
    """Enqueue the analyst task, transitioning feature to 'analyzing' status.

    For the GitHub backend, transparently auto-converts a raw labelled issue
    into a harness feature first (so the user can press ``i`` on a freshly
    labelled issue without invoking ``/convertforagent`` manually).
    """
    from datetime import UTC, datetime

    state_mgr = create_state_manager(config)

    if config.storage_backend == "github":
        try:
            await state_mgr.get(feature_id)
        except KeyError:
            await _convert_raw_issue(feature_id, config)

    state = await state_mgr.update(
        feature_id,
        lambda s: s.with_status(FeatureStatus.analyzing).with_event("pipeline_started"),
    )

    work_dir_str: str | None = None

    if config.storage_backend == "github":
        branch_name = state.branch_name or feature_id
        brief_content = await _fetch_brief_for_feature(state, config)

        store = create_artifact_store(config, feature_id=branch_name)
        try:
            await store._ensure_clone()
            await store._checkout_or_create(branch_name)

            work_dir = store.get_work_dir()
            (work_dir / "brief.md").write_text(brief_content, encoding="utf-8")
            work_dir_str = str(work_dir)

            await store.upload(artifact_path(feature_id, "brief.md"), brief_content)
        finally:
            await store.close()

        state = await state_mgr.update(
            feature_id,
            lambda s: s.model_copy(update={
                "branch_name": branch_name,
                "worktree_path": work_dir_str,
                "updated_at": datetime.now(UTC),
            }),
        )

    queue = create_task_queue(config, "analyst-queue")
    try:
        task = TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-analyst",
            input_artifacts=[artifact_path(feature_id, "brief.md")],
            output_artifact=phase_artifact_path(feature_id, "spec", 1),
            agent_role="analyst",
            state_issue_number=state.state_issue_number,
            work_dir=work_dir_str,
        )
        await queue.ensure_exists()
        await queue.send_task(task)
        log.info("Enqueued analyst task for %s", feature_id)
    finally:
        await queue.close()
```

The diff is essentially: insert the GitHub pre-flight block before the existing `state_mgr.update(...)`. Everything else is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brainstorm_github.py -v`
Expected: PASS for all tests, including the new pre-flight class and existing `test_enqueue_planner_sends_correct_task` (which uses an Azure-style config with `state_mgr.update` mocked — must remain green; if it had `storage_backend="github"` it now requires `state_mgr.get` to be mocked too).

If `test_enqueue_planner_sends_correct_task` (line 121) fails because `state_mgr.get` is unmocked on the new code path, update its `_make_state_mgr` call to also stub `.get` returning a non-raw `FeatureState`. Specifically, modify `_make_state_mgr` in `tests/test_brainstorm_github.py:44-51` to:

```python
def _make_state_mgr(feature_id: str = _FEATURE_ID) -> MagicMock:
    from agentharness.models import FeatureState, FeatureStatus
    mgr = MagicMock()
    mgr.create = AsyncMock()
    mgr.get = AsyncMock(
        return_value=FeatureState(feature_id=feature_id, status=FeatureStatus.brainstormed)
    )
    mgr.update = AsyncMock(
        return_value=FeatureState(feature_id=feature_id, status=FeatureStatus.analyzing)
    )
    return mgr
```

Then re-run: `.venv/bin/pytest tests/test_brainstorm_github.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/brainstorm.py tests/test_brainstorm_github.py
git commit -m "feat: auto-convert raw issues during enqueue_planner on GitHub backend"
```

---

## Task 8: TUI guard for raw features in `action_open_state_change`

**Files:**
- Modify: `agentharness/tui.py:653-692` (`action_open_state_change` method)
- Test: `tests/test_tui_state_change.py` (new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tui_state_change.py`:

```python
# ---------------------------------------------------------------------------
# action_open_state_change — raw feature guard
# ---------------------------------------------------------------------------


class TestActionOpenStateChangeRawGuard:
    """The TUI guard logic is small enough to test by hand-rolling a stub.

    We only verify the decision: 'is_raw → notify-and-return; not raw → fall
    through to push_screen'. We don't drive the full Textual app — that is
    covered by manual smoke tests, matching the rest of this module's style.
    """

    def test_raw_feature_emits_notification_and_returns(self):
        from agentharness.models import FeatureState, FeatureStatus

        raw = FeatureState(feature_id="feat-raw", status=FeatureStatus.brainstormed)
        # Sanity check the precondition we rely on
        assert raw.is_raw is True

        notifications: list[tuple[str, str]] = []
        opened: list[str] = []

        def notify(msg: str, severity: str = "information") -> None:
            notifications.append((msg, severity))

        def push_screen(_modal, _on_result) -> None:
            opened.append("modal")

        # Pure-logic transcription of action_open_state_change for the
        # is_raw path — verifies the new branch in isolation.
        def action(state: FeatureState) -> None:
            if state.is_raw:
                notify("Convert to harness feature first (press i)", "warning")
                return
            push_screen(object(), lambda _r: None)

        action(raw)
        assert notifications == [("Convert to harness feature first (press i)", "warning")]
        assert opened == []

    def test_initialized_feature_opens_modal(self):
        from agentharness.models import FeatureState, FeatureStatus

        initialized = FeatureState(
            feature_id="feat-init", status=FeatureStatus.analyzing,
        ).with_event("brief_uploaded")
        assert initialized.is_raw is False

        notifications: list[tuple[str, str]] = []
        opened: list[str] = []

        def notify(msg: str, severity: str = "information") -> None:
            notifications.append((msg, severity))

        def push_screen(_modal, _on_result) -> None:
            opened.append("modal")

        def action(state: FeatureState) -> None:
            if state.is_raw:
                notify("Convert to harness feature first (press i)", "warning")
                return
            push_screen(object(), lambda _r: None)

        action(initialized)
        assert notifications == []
        assert opened == ["modal"]
```

The test is a behavioural transcription, mirroring the comment in the existing `test_tui_state_change.py` header that explicit Textual pilot tests are deliberately avoided. The point of the test is that the new branch (raw guard) precedes the modal-open branch.

- [ ] **Step 2: Run test to verify it passes for the trivial direction and fails for the real one**

Run: `.venv/bin/pytest tests/test_tui_state_change.py::TestActionOpenStateChangeRawGuard -v`
Expected: PASS — both tests verify pure logic that already works given `is_raw` from Task 1.

(This task is the *minimal* observable contract test for the property-driven guard. The actual TUI plumbing is verified by Step 4 below — running the TUI manually in Step 6.)

- [ ] **Step 3: Add the guard to `tui.py`**

In `agentharness/tui.py`, modify `action_open_state_change` (around line 653). Insert the new check after the `state is None` block but before the `state.status == FeatureStatus.done` block:

```python
    def action_open_state_change(self) -> None:
        feature_id = self.query_one(FeatureList).selected_feature_id()
        if not feature_id:
            self.notify("No feature selected.", severity="warning")
            return
        state = next((s for s in self._states if s.feature_id == feature_id), None)
        if state is None:
            self.notify("Selected feature has no cached state.", severity="warning")
            return
        if state.is_raw:
            self.notify(
                "Convert to harness feature first (press i)",
                severity="warning",
            )
            return
        if state.status == FeatureStatus.done:
            self.notify(
                "State change unavailable for completed features.",
                severity="warning",
            )
            return

        # ... rest of method unchanged ...
```

The exact insertion is a 5-line block; do not touch any other branch of the method.

- [ ] **Step 4: Run unit tests**

Run: `.venv/bin/pytest tests/test_tui_state_change.py -v`
Expected: PASS — all existing `_options_for` tests + the two new guard tests.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 6: Manual TUI smoke test (one-time)**

Because Textual headless tests are intentionally avoided in this codebase, perform a manual confirmation that the guard works end-to-end. Skip this step if no GitHub backend is configured locally.

1. Label a test issue with the configured `feature_marker` label, leaving its body without a state block.
2. Run `agentharness watch` and wait for the next refresh (≤2s).
3. Verify the issue appears as `◎  {short-id}  □□□□□  brainstormed`.
4. Select that row, press `S` (state change). Expected: notification "Convert to harness feature first (press i)" appears, no modal opens.
5. Press `i`. Expected: silent conversion, then transition to `analyzing` on the next refresh.
6. With the now-initialised feature selected, press `S` again. Expected: state-change modal opens normally.

- [ ] **Step 7: Commit**

```bash
git add agentharness/tui.py tests/test_tui_state_change.py
git commit -m "feat: guard TUI state-change action against raw features"
```

---

## Final verification

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests pass; no warnings introduced.

- [ ] **Step 2: Static check imports**

Run: `.venv/bin/python -c "from agentharness import brainstorm, github_state, models, tui"`
Expected: No `ImportError` / no syntax error.

- [ ] **Step 3: Confirm the spec's flows work end-to-end (manual, GitHub backend)**

Refer to spec §"User-visible flows" Flow A, B, C. Walk through each in your live repo (one labelled issue is enough to exercise all three). All three must behave exactly as the spec describes.

---

## Self-review (performed during plan authoring)

**Spec coverage:**
| Spec section | Covered by |
|---|---|
| FR-1 raw issues appear as synthetic features | Tasks 3, 4 |
| FR-2 `patch_existing_issue` method | Task 5 |
| FR-3 `_convert_raw_issue` helper | Task 6 |
| FR-4 `enqueue_planner` auto-converts on GitHub | Task 7 |
| FR-5 TUI guard for raw features | Task 8 |
| FR-6 TUI `i` key works on raw features | Tasks 6+7 (no TUI change required) |
| NFR-1 performance | Task 4 design (no extra API calls); Task 6 (bounded ≤4 calls) |
| NFR-2 security | No new credentials/scopes; reuses `GitHubClient`. Verified by inspection. |
| NFR-3 idempotency | Task 5 idempotent test; Task 6 422-tolerant branch creation. |
| NFR-4 observability | Task 4 drops the per-refresh warning; Task 5/6 emit `log.info` on conversion. |
| Arch amendment 1 (`is_raw` property) | Task 1 |
| Arch amendment 2 (shared `slug_title`) | Task 2 |
| Arch amendment 3 (`_slug_from_brief` delegates) | Task 2 |
| Arch amendment 4 (drop `log.warning`) | Task 4 |
| Arch amendment 5 (`get()` semantics docstring) | Task 4 (docstring updated as part of `list_features` rewrite — note added in code that `get()` semantics are unchanged) |
| Arch amendment 6 (resource management in `_convert_raw_issue`) | Task 6 (`try/finally` around all three resources) |

**Type consistency:** `slug_title`, `_synthesize_raw_state`, `is_raw`, `patch_existing_issue`, and `_convert_raw_issue` signatures match across tasks where they're cross-referenced. Test imports use the same names throughout.

**Placeholder scan:** No "TBD", "implement later", or "similar to Task N" placeholders. Every code step shows the actual code.

**Note on Arch amendment 5:** The architecture review asked for a `get()` docstring clarification noting that `get()` keeps raising `KeyError` for raw issues. `get()` itself is not modified in this plan (its behaviour is unchanged), so the existing docstring remains correct in spirit. If a follow-up wants an explicit "even when `list_features()` would surface them" line, that's a one-line doc tweak with no functional change — captured here as a tracked but non-blocking item.
