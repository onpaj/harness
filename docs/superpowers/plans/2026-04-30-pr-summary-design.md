# PR Summary Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current operational-log GitHub PR title and body with a human-readable summary derived from the user's brief and the developer agent's own work narrative; fall back to the current log-style format whenever any input is missing.

**Architecture:** The developer agent emits a free-form `## PR Summary` section in its output artifact. The dispatcher reads `brief.md` and the last completed developer impl artifact via `ArtifactStorage`, extracts the title and summary with three small line-walk helpers, and passes pre-rendered strings to `GitHubStateManager.open_review` via two new keyword-only kwargs (`pr_title`, `pr_summary`). `github_state.py` becomes a thin renderer that picks between the developer-authored body and the existing log-style body. The artifact store handle is threaded explicitly through `dispatch_after_completion` → `_dispatch_serial_next` / `_dispatch_review_result` → `_open_feature_pr` → `_build_pr_content`. All artifact-read failures are caught at the assembly boundary; the system degrades to current behaviour bit-for-bit when any input is missing.

**Tech Stack:** Python 3.11+, Pydantic, asyncio, pytest + pytest-asyncio, `unittest.mock` (`AsyncMock`, `MagicMock`).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `.agents/developer.md` | Developer agent prompt | Add `## PR Summary` to required output sections; restructure template so `## Status` block lives at the end with `## PR Summary` directly above it; add a concrete example |
| `agentharness/dispatcher.py` | State transitions, fan-out/in, dispatch | Add 3 sync helpers (`_extract_brief_title`, `_extract_pr_summary`, `_last_developer_artifact`) + 1 async helper (`_build_pr_content`); thread `store` keyword-only kwarg through `dispatch_after_completion`, `_dispatch_serial_next`, `_dispatch_review_result`, `_open_feature_pr`; delete dead `_build_pr_body` at line 610 |
| `agentharness/github_state.py` | GitHub API state backend | Update `open_review` signature to accept `pr_title` and `pr_summary` keyword-only kwargs; split body assembly into `_build_log_body` and `_compose_pr_body` helpers; pick branch based on `pr_summary` |
| `agentharness/storage_protocol.py` | Backend protocol definitions | Update `StateBackend.open_review` signature with two keyword-only optional kwargs |
| `agentharness/run_task.py` | Single-task subprocess runner | One-line change at line 128 to pass `store=store` |
| `tests/test_dispatcher.py` | Dispatcher unit tests | Add tests for 3 sync helpers + `_build_pr_content` (async fake store); update existing `_open_feature_pr` tests for new keyword args |
| `tests/test_dispatcher_github.py` | GitHub-specific dispatcher tests | Update existing `_open_feature_pr` mocks to allow the new `store` parameter and new `open_review` kwargs |
| `tests/test_github_state.py` | State backend unit tests | Add tests for `open_review` body branching (4 cases: both kwargs, pr_summary only, pr_title only, neither) |

No new files in production code or tests.

---

## Self-contained checklist for the executor

Each task below is independently committable. Tests come first (RED), then minimal implementation (GREEN), then commit. Tasks are ordered so each subsequent task can run with the previous merged: prompt change is harmless on its own; sync helpers are pure and side-effect free; async helper depends on sync helpers; protocol/state-manager update is decoupled from dispatcher; threading the kwarg lands last because it touches every existing test that calls `_dispatch_serial_next`/`_dispatch_review_result`.

---

## Task 1: Add `## PR Summary` section to developer agent prompt

**Files:**
- Modify: `.agents/developer.md`

**Why this change:** The developer agent is the only context-aware author of the impl artifact. The spec requires a free-form `## PR Summary` section that the dispatcher will later read and forward to the GitHub PR body.

**Output template restructure:** The existing template puts `## Status` at the *top* (right after the title). The new template moves `## Status` to the *end* with `## PR Summary` directly above it. This matches the design and gives the line-walk parser a stable anchor.

The existing `_DEV_STATUS_RE` regex in `dispatcher.py` uses `re.MULTILINE`, so it will match `## Status\n{VALUE}` regardless of position. No regex change is needed.

- [ ] **Step 1: Replace the output template in `.agents/developer.md`**

Replace the entire `## Output artifact format` section (lines 45–72) with:

```markdown
## Output artifact format

After the task is complete, write your output summary in this exact section order:

```markdown
# Implementation: {task name}

## What was implemented
{Brief description}

## Files created/modified
- `path/to/file.py` — {what it contains}

## Tests
{List of test files and what they cover}

## How to verify
{Steps to run and verify the implementation}

## Notes
{Any deviations, assumptions, concerns}

## PR Summary
{Two short paragraphs of free-form markdown describing what was built and why,
written for a human reviewer who has not seen the spec. No schema. No checklist.}

### Changes
- `path/to/file.py` — one-sentence rationale
- `another/file.py` — one-sentence rationale

## Status
DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
```

Use `DONE_WITH_CONCERNS` if any subagent raised unresolved concerns.
Use `BLOCKED` if the task could not be completed after re-dispatch attempts.
Use `NEEDS_CONTEXT` if information required to complete the task was not available in the context file.

### `## PR Summary` example

```markdown
## PR Summary
Added a free-form summary section to the developer agent output so reviewers see
what changed at a glance instead of a phase log. The dispatcher reads this section
from the last completed impl artifact and forwards it as the PR body when opening
the feature PR.

### Changes
- `agentharness/dispatcher.py` — added `_extract_pr_summary` and `_build_pr_content`
- `agentharness/github_state.py` — `open_review` now picks between summary and log body
- `.agents/developer.md` — required output now includes a `## PR Summary` section
```

Avoid putting `## ` headings inside fenced code blocks within the summary —
the parser stops at any line starting with `## `, which would truncate the summary.
```

- [ ] **Step 2: Verify the file parses as the existing harness expects**

Run: `python -c "from agentharness.prompt_builder import load_agent_definition; from pathlib import Path; d = load_agent_definition(Path('.agents/developer.md')); print(d.id, d.allowed_tools, d.output_parsing)"`

Expected output: `developer ['bash', 'read', 'write', 'task'] none`

- [ ] **Step 3: Commit**

```bash
git add .agents/developer.md
git commit -m "feat: add ## PR Summary section to developer agent prompt"
```

---

## Task 2: Add `_extract_brief_title` helper with tests

**Files:**
- Modify: `agentharness/dispatcher.py` (add helper at module bottom, above `_open_feature_pr`)
- Test: `tests/test_dispatcher.py` (add `TestExtractBriefTitle` class)

**Contract:** `_extract_brief_title(content: str) -> str`
- Returns the first `# Heading` text with leading `#` characters and surrounding whitespace stripped, or
- The first non-empty stripped line if no `# heading` is present, or
- `""` if input is empty or whitespace-only.

The helper is pure — no I/O, no mutation, O(n).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dispatcher.py` (after the `TestParseAnalystStatus` class):

```python
class TestExtractBriefTitle:
    def test_returns_h1_heading_text(self):
        from agentharness.dispatcher import _extract_brief_title
        content = "# Add PR Summary Design\n\nSome body text."
        assert _extract_brief_title(content) == "Add PR Summary Design"

    def test_strips_multiple_leading_hashes(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("### Deep Heading\nbody") == "Deep Heading"

    def test_strips_surrounding_whitespace(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("#   Padded Title   \nbody") == "Padded Title"

    def test_first_heading_wins_when_multiple_present(self):
        from agentharness.dispatcher import _extract_brief_title
        content = "intro line\n\n# First Heading\n\n# Second Heading"
        assert _extract_brief_title(content) == "First Heading"

    def test_falls_back_to_first_non_empty_line_when_no_heading(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("\n\n  first real line  \nsecond") == "first real line"

    def test_returns_empty_string_for_empty_input(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("") == ""

    def test_returns_empty_string_for_whitespace_only(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("   \n\n  \t\n") == ""
```

- [ ] **Step 2: Run tests — verify they fail with ImportError**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestExtractBriefTitle -v`

Expected: ImportError or AttributeError — `_extract_brief_title` does not exist.

- [ ] **Step 3: Implement `_extract_brief_title`**

Add to `agentharness/dispatcher.py` immediately above the `_open_feature_pr` function (around line 732):

```python
def _extract_brief_title(content: str) -> str:
    """Return a human-readable title from a brief.

    Priority:
      1. First line starting with '#' — return text with leading '#' chars
         and surrounding whitespace stripped.
      2. First non-empty stripped line.
      3. Empty string when input has no usable content.

    Pure: no I/O, O(n) on input length.
    """
    first_non_empty: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if first_non_empty is None:
            first_non_empty = line
    return first_non_empty or ""
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestExtractBriefTitle -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _extract_brief_title helper to dispatcher"
```

---

## Task 3: Add `_extract_pr_summary` helper with tests

**Files:**
- Modify: `agentharness/dispatcher.py` (add helper directly below `_extract_brief_title`)
- Test: `tests/test_dispatcher.py` (add `TestExtractPrSummary` class)

**Contract:** `_extract_pr_summary(impl_content: str) -> str | None`
- Returns the markdown content from the line *after* `## PR Summary` up to (but not including) the next line that starts with `## `, or end of file.
- Returns `None` if the section is absent.
- Returns `None` if the body, after rstripping, is empty or whitespace-only.
- Returns `None` if the body contains only an empty `### Changes` subheading with no list items underneath.
- Trailing whitespace is stripped; subheadings such as `### Changes` are preserved verbatim.
- Implementation is a line-walk scanner (not regex) to avoid multi-line lookahead pitfalls.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dispatcher.py` (after the `TestExtractBriefTitle` class):

```python
class TestExtractPrSummary:
    def test_returns_section_body_until_next_h2(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "# Implementation: foo\n"
            "## Notes\n"
            "n/a\n"
            "## PR Summary\n"
            "Implemented X to do Y.\n"
            "\n"
            "### Changes\n"
            "- `file.py` — added foo\n"
            "## Status\n"
            "DONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert result.startswith("Implemented X to do Y.")
        assert "### Changes" in result
        assert "- `file.py` — added foo" in result
        assert "## Status" not in result
        assert "DONE" not in result

    def test_returns_section_body_until_eof_when_no_following_h2(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nA standalone summary at end of file.\n"
        assert _extract_pr_summary(impl) == "A standalone summary at end of file."

    def test_returns_none_when_section_absent(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## Notes\nn/a\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_none_when_body_is_whitespace_only(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\n   \n\n\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_none_when_body_is_only_empty_changes_heading(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\n### Changes\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_summary_when_changes_has_at_least_one_item(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "### Changes\n"
            "- `file.py` — explanation\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "### Changes" in result

    def test_preserves_internal_blank_lines(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "Paragraph one.\n"
            "\n"
            "Paragraph two.\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "Paragraph one." in result
        assert "Paragraph two." in result

    def test_section_at_top_of_file(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nFirst-thing summary.\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) == "First-thing summary."

    def test_h3_heading_inside_body_does_not_terminate(self):
        from agentml := None  # placeholder noise: the next test asserts ### does not stop the scanner
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "Intro.\n"
            "### Changes\n"
            "- `a.py` — note\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "### Changes" in result
        assert "- `a.py` — note" in result

    def test_rstrips_trailing_whitespace(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nSummary text.\n\n\n   \n## Status\nDONE\n"
        result = _extract_pr_summary(impl)
        assert result is not None
        assert result == "Summary text."

    def test_returns_none_for_empty_input(self):
        from agentharness.dispatcher import _extract_pr_summary
        assert _extract_pr_summary("") is None
```

> Fix: remove the bogus walrus line in `test_h3_heading_inside_body_does_not_terminate` (it was scratch). The corrected test:

```python
    def test_h3_heading_inside_body_does_not_terminate(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "Intro.\n"
            "### Changes\n"
            "- `a.py` — note\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "### Changes" in result
        assert "- `a.py` — note" in result
```

- [ ] **Step 2: Run tests — verify they fail with ImportError**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestExtractPrSummary -v`

Expected: ImportError or AttributeError on every test.

- [ ] **Step 3: Implement `_extract_pr_summary`**

Add to `agentharness/dispatcher.py` directly below `_extract_brief_title`:

```python
_PR_SUMMARY_HEADER = "## PR Summary"


def _extract_pr_summary(impl_content: str) -> str | None:
    """Return the body of the '## PR Summary' section, or None if absent/empty.

    Scanner contract:
      BEFORE_SECTION → line == '## PR Summary' → IN_SECTION
      IN_SECTION → line starts with '## ' → DONE (stop collecting)
      IN_SECTION → else → append line to buffer

    Post-processing:
      • Join buffer lines, rstrip trailing whitespace.
      • Empty / whitespace-only buffer → None.
      • Buffer whose only non-blank content is a '### Changes' line with no
        list items → None.
      • Otherwise → return the rstripped body. Subheadings (e.g. '### Changes')
        are preserved verbatim.
    """
    in_section = False
    buffer: list[str] = []
    for line in impl_content.splitlines():
        stripped = line.strip()
        if not in_section:
            if stripped == _PR_SUMMARY_HEADER:
                in_section = True
            continue
        if line.startswith("## "):
            break
        buffer.append(line)

    body = "\n".join(buffer).rstrip()
    if not body.strip():
        return None

    non_empty_lines = [ln for ln in body.splitlines() if ln.strip()]
    if non_empty_lines == ["### Changes"]:
        return None

    return body
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestExtractPrSummary -v`

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _extract_pr_summary helper to dispatcher"
```

---

## Task 4: Add `_last_developer_artifact` helper with tests

**Files:**
- Modify: `agentharness/dispatcher.py` (add helper directly below `_extract_pr_summary`)
- Test: `tests/test_dispatcher.py` (add `TestLastDeveloperArtifact` class)

**Contract:** `_last_developer_artifact(state: FeatureState) -> str | None`
- Walks `state.tasks` in insertion order.
- Returns the `output_artifact` of the *last* `TaskEntry` where:
  - `phase == "developing"`, AND
  - `status == TaskStatus.completed`, AND
  - `output_artifact is not None`.
- Returns `None` if no such entry exists.

`state.tasks` is a list and Pydantic preserves insertion order — the test below locks that invariant.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dispatcher.py` (after `TestExtractPrSummary`):

```python
class TestLastDeveloperArtifact:
    def _state(self, tasks: list[TaskEntry]) -> FeatureState:
        return FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.developing,
            tasks=tasks,
        )

    def test_returns_none_when_no_tasks(self):
        from agentharness.dispatcher import _last_developer_artifact
        assert _last_developer_artifact(self._state([])) is None

    def test_returns_none_when_no_completed_developer_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.in_progress,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) is None

    def test_returns_none_when_completed_task_has_no_artifact(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact=None,
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) is None

    def test_returns_artifact_for_single_completed_developer_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r1.md"

    def test_returns_artifact_of_last_matching_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/a.r1.md",
            ),
            TaskEntry(
                task_id="t2",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/b.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/b.r1.md"

    def test_skips_non_developer_phases(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="d1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
            TaskEntry(
                task_id="r1",
                phase="reviewing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/review/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r1.md"

    def test_returns_revision_artifact_when_multiple_revisions(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="d1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
            TaskEntry(
                task_id="d1-rev",
                phase="developing",
                status=TaskStatus.completed,
                revision=2,
                output_artifact="artifacts/x/impl/main.r2.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r2.md"
```

- [ ] **Step 2: Run tests — verify they fail with ImportError**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestLastDeveloperArtifact -v`

Expected: ImportError on every test.

- [ ] **Step 3: Implement `_last_developer_artifact`**

Add to `agentharness/dispatcher.py` directly below `_extract_pr_summary`:

```python
def _last_developer_artifact(state: FeatureState) -> str | None:
    """Return the output_artifact of the last completed developer task.

    Walks state.tasks in insertion order; returns the path of the last entry
    whose phase == 'developing', status == completed, and output_artifact is set.
    Returns None when no such entry exists.
    """
    last: str | None = None
    for entry in state.tasks:
        if (
            entry.phase == "developing"
            and entry.status == TaskStatus.completed
            and entry.output_artifact is not None
        ):
            last = entry.output_artifact
    return last
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestLastDeveloperArtifact -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _last_developer_artifact helper to dispatcher"
```

---

## Task 5: Add async `_build_pr_content` helper with tests

**Files:**
- Modify: `agentharness/dispatcher.py` (add `_build_pr_content` directly below `_last_developer_artifact`)
- Test: `tests/test_dispatcher.py` (add `TestBuildPrContent` class)

**Contract:** `async _build_pr_content(state, store) -> tuple[str | None, str | None]`
- Returns `(pr_title_or_None, pr_summary_or_None)`.
- When `store is None` → `(None, None)` immediately, no logging beyond DEBUG.
- Otherwise:
  - Try to download `artifacts/{feature_id}/brief.md`. On any exception or empty extraction → `pr_title = None`, log INFO with the reason.
  - Use `_last_developer_artifact(state)` to find the last impl path. If none → `pr_summary = None`, log INFO.
  - Try to download the impl path; extract `## PR Summary` → `pr_summary`. On any exception → `pr_summary = None`, log INFO.
- Catches any unexpected exception with `log.exception` and falls back to `(None, None)`. Never raises.

**Logging contract** (one line each, all INFO unless noted):

| Event | Format |
|---|---|
| Brief artifact missing/unreadable | `"[%s] PR title fallback: brief.md not available (%s)" % (feature_id, reason)` |
| Brief heading extraction empty | `"[%s] PR title fallback: brief.md has no heading or content" % feature_id` |
| Impl artifact missing/unreadable | `"[%s] PR summary fallback: impl artifact not available (%s)" % (feature_id, reason)` |
| `## PR Summary` section absent or empty | `"[%s] PR summary fallback: no ## PR Summary section in impl artifact" % feature_id` |
| Unexpected exception (ERROR + stack trace via `log.exception`) | `"[%s] Unexpected error building PR content; falling back to defaults" % feature_id` |

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dispatcher.py` (after `TestLastDeveloperArtifact`):

```python
class _FakeStore:
    """Minimal in-memory ArtifactStorage for unit tests."""

    def __init__(self, files: dict[str, str] | None = None, fail_paths: set[str] | None = None):
        self._files = files or {}
        self._fail = fail_paths or set()

    async def download(self, path: str) -> str:
        if path in self._fail:
            raise RuntimeError(f"simulated download failure for {path}")
        try:
            return self._files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    async def upload(self, path: str, content): pass
    async def exists(self, path: str) -> bool: return path in self._files
    async def close(self) -> None: pass
    def get_work_dir(self): return None
    async def commit_workdir_changes(self, message: str) -> bool: return False


class TestBuildPrContent:
    def _state_with_dev_task(
        self,
        feature_id: str = "feat-x",
        impl_path: str = "artifacts/feat-x/impl/main.r1.md",
    ) -> FeatureState:
        return FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.done,
            tasks=[
                TaskEntry(
                    task_id="t1",
                    phase="developing",
                    status=TaskStatus.completed,
                    output_artifact=impl_path,
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_returns_none_none_when_store_is_none(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        assert await _build_pr_content(state, None) == (None, None)

    @pytest.mark.asyncio
    async def test_returns_title_and_summary_when_both_artifacts_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Add PR Summary Design\n\nbody.",
            "artifacts/feat-x/impl/main.r1.md": (
                "## Notes\nn/a\n"
                "## PR Summary\nImplemented PR summary support.\n\n"
                "### Changes\n- `dispatcher.py` — added helpers\n"
                "## Status\nDONE\n"
            ),
        })
        title, summary = await _build_pr_content(state, store)
        assert title == "Add PR Summary Design"
        assert summary is not None
        assert "Implemented PR summary support." in summary
        assert "### Changes" in summary
        assert "## Status" not in summary

    @pytest.mark.asyncio
    async def test_brief_missing_returns_none_title_summary_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nA summary.\n## Status\nDONE\n",
        })
        title, summary = await _build_pr_content(state, store)
        assert title is None
        assert summary == "A summary."

    @pytest.mark.asyncio
    async def test_brief_empty_returns_none_title(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "   \n\n",
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nx.\n## Status\nDONE\n",
        })
        title, _ = await _build_pr_content(state, store)
        assert title is None

    @pytest.mark.asyncio
    async def test_impl_missing_returns_none_summary_title_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Title\n",
        })
        title, summary = await _build_pr_content(state, store)
        assert title == "Title"
        assert summary is None

    @pytest.mark.asyncio
    async def test_no_completed_developer_task_returns_none_summary(self):
        from agentharness.dispatcher import _build_pr_content
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.done, tasks=[])
        store = _FakeStore({"artifacts/feat-x/brief.md": "# Title\n"})
        title, summary = await _build_pr_content(state, store)
        assert title == "Title"
        assert summary is None

    @pytest.mark.asyncio
    async def test_pr_summary_section_absent_returns_none_summary(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Title\n",
            "artifacts/feat-x/impl/main.r1.md": "## Notes\nn/a\n## Status\nDONE\n",
        })
        _, summary = await _build_pr_content(state, store)
        assert summary is None

    @pytest.mark.asyncio
    async def test_brief_download_exception_falls_back(self, caplog):
        import logging
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore(
            files={"artifacts/feat-x/impl/main.r1.md": "## PR Summary\nbody.\n"},
            fail_paths={"artifacts/feat-x/brief.md"},
        )
        with caplog.at_level(logging.INFO, logger="agentharness.dispatcher"):
            title, summary = await _build_pr_content(state, store)
        assert title is None
        assert summary == "body."
        assert any("PR title fallback" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_impl_download_exception_falls_back(self, caplog):
        import logging
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore(
            files={"artifacts/feat-x/brief.md": "# Title\n"},
            fail_paths={"artifacts/feat-x/impl/main.r1.md"},
        )
        with caplog.at_level(logging.INFO, logger="agentharness.dispatcher"):
            title, summary = await _build_pr_content(state, store)
        assert title == "Title"
        assert summary is None
        assert any("PR summary fallback" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_never_raises_on_unexpected_exception(self):
        from agentharness.dispatcher import _build_pr_content

        class BoomStore:
            async def download(self, path: str):
                raise ValueError("boom")
            async def upload(self, path, content): pass
            async def exists(self, path): return False
            async def close(self): pass
            def get_work_dir(self): return None
            async def commit_workdir_changes(self, message): return False

        state = self._state_with_dev_task()
        # Must not raise
        title, summary = await _build_pr_content(state, BoomStore())
        assert title is None
        assert summary is None
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestBuildPrContent -v`

Expected: ImportError or AttributeError on every test.

- [ ] **Step 3: Implement `_build_pr_content`**

Update the import block at the top of `agentharness/dispatcher.py` to include `ArtifactStorage`:

```python
from agentharness.storage_protocol import ArtifactStorage, StateBackend, TaskQueue
```

Add `_build_pr_content` to `agentharness/dispatcher.py` directly below `_last_developer_artifact`:

```python
_BRIEF_PATH_TEMPLATE = "artifacts/{feature_id}/brief.md"


async def _build_pr_content(
    state: FeatureState,
    store: ArtifactStorage | None,
) -> tuple[str | None, str | None]:
    """Assemble (pr_title, pr_summary) for the GitHub PR; never raises.

    Returns (None, None) when *store* is None — the caller falls back to
    log-style PR content. Otherwise downloads brief.md and the last completed
    developer impl artifact, extracts title + summary, and logs INFO on each
    fallback path. Unexpected exceptions are caught with log.exception.
    """
    if store is None:
        return None, None

    feature_id = state.feature_id
    pr_title: str | None = None
    pr_summary: str | None = None

    try:
        brief_path = _BRIEF_PATH_TEMPLATE.format(feature_id=feature_id)
        try:
            brief_content = await store.download(brief_path)
        except Exception as exc:
            log.info(
                "[%s] PR title fallback: brief.md not available (%s)",
                feature_id, exc,
            )
        else:
            extracted = _extract_brief_title(brief_content)
            if extracted:
                pr_title = extracted
            else:
                log.info(
                    "[%s] PR title fallback: brief.md has no heading or content",
                    feature_id,
                )

        impl_path = _last_developer_artifact(state)
        if impl_path is None:
            log.info(
                "[%s] PR summary fallback: no completed developer task in state",
                feature_id,
            )
        else:
            try:
                impl_content = await store.download(impl_path)
            except Exception as exc:
                log.info(
                    "[%s] PR summary fallback: impl artifact not available (%s)",
                    feature_id, exc,
                )
            else:
                pr_summary = _extract_pr_summary(impl_content)
                if pr_summary is None:
                    log.info(
                        "[%s] PR summary fallback: no ## PR Summary section in impl artifact",
                        feature_id,
                    )

        return pr_title, pr_summary

    except Exception:
        log.exception(
            "[%s] Unexpected error building PR content; falling back to defaults",
            feature_id,
        )
        return None, None
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestBuildPrContent -v`

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add _build_pr_content helper for PR title and summary"
```

---

## Task 6: Update `StateBackend.open_review` protocol and `GitHubStateManager.open_review` body branching

**Files:**
- Modify: `agentharness/storage_protocol.py` (line 54 — `open_review` signature)
- Modify: `agentharness/github_state.py` (lines 454–505 — `open_review` body)
- Test: `tests/test_github_state.py` (extend `open_review` tests; existing tests at line 612 and 636 must keep passing)

**Goal:** `open_review` accepts two new keyword-only optional kwargs (`pr_title`, `pr_summary`) and picks between the developer-authored body and the existing log-style body. The Azure backend has no `open_review` and is unaffected.

Body shape when `pr_summary` is non-empty:

```
{pr_summary}

---

Closes #{state_issue_number}

### Tokens used
{tokens_line}
```

Body shape when `pr_summary` is None or empty: bit-for-bit current log-style body.

The `Closes #{N}` line is omitted when `state.state_issue_number` is `None` in *both* branches.

- [ ] **Step 1: Write the failing tests in `tests/test_github_state.py`**

Add a new section near the existing `open_review` tests:

```python
# ---------------------------------------------------------------------------
# open_review body branching (Task 6)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_review_uses_pr_title_when_provided():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 7})
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title="Add PR Summary Design", pr_summary=None)

    args, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == "Add PR Summary Design"


@pytest.mark.asyncio
async def test_open_review_uses_default_title_when_pr_title_none():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 7})
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=None)

    args, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == f"{state.feature_id}: implementation complete"


@pytest.mark.asyncio
async def test_open_review_uses_pr_summary_body_when_provided():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 12})
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    summary = "Implemented X.\n\n### Changes\n- `file.py` — note"
    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=summary)

    args, kwargs = client.create_pull_request.call_args
    body = kwargs["body"]
    # Developer summary comes first
    assert body.startswith("Implemented X.")
    assert "### Changes" in body
    # Followed by separator + closes line + tokens footer
    assert "\n\n---\n\n" in body
    assert "Closes #12" in body
    assert "### Tokens used" in body
    # Log-style sections are NOT present
    assert "## Feature:" not in body
    assert "### Phases" not in body


@pytest.mark.asyncio
async def test_open_review_uses_log_body_when_pr_summary_none():
    """Bit-for-bit current behaviour when pr_summary is None."""
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 12})
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=None)

    args, kwargs = client.create_pull_request.call_args
    body = kwargs["body"]
    # Log-style markers present
    assert "## Feature:" in body
    assert "### Phases" in body
    assert "### Tasks" in body
    assert "### Tokens used" in body
    assert "Closes #12" in body


@pytest.mark.asyncio
async def test_open_review_omits_closes_line_when_no_issue_number():
    state = _make_state(status=FeatureStatus.done)
    # Note: state_issue_number is None
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary="Body.")

    args, kwargs = client.create_pull_request.call_args
    assert "Closes #" not in kwargs["body"]


@pytest.mark.asyncio
async def test_open_review_back_compat_no_kwargs():
    """Existing callers that omit both kwargs still work."""
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 1})
    client = MagicMock()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    pr_url = await mgr.open_review(state.feature_id)
    assert pr_url == "https://x"
    args, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == f"{state.feature_id}: implementation complete"
    assert "## Feature:" in kwargs["body"]
```

- [ ] **Step 2: Run tests — verify the 6 new tests fail**

Run: `.venv/bin/pytest tests/test_github_state.py -v -k "open_review_uses or open_review_omits or back_compat"`

Expected: 6 failures (TypeError on unexpected keyword argument, or assertion failures).

- [ ] **Step 3: Update protocol signature**

Edit `agentharness/storage_protocol.py` line 54:

```python
class StateBackend(Protocol):
    async def create(self, state: FeatureState, brief_content: str = "") -> None: ...
    async def get(self, feature_id: str) -> FeatureState: ...
    async def update(
        self,
        feature_id: str,
        updater: Callable[[FeatureState], FeatureState],
    ) -> FeatureState: ...
    async def set_worktree_path(self, feature_id: str, worktree_path: str) -> None: ...
    async def set_cleanup_warning(self, feature_id: str, message: str) -> None: ...
    async def list_features(self) -> list[FeatureState]: ...
    async def open_review(
        self,
        feature_id: str,
        *,
        pr_title: str | None = None,
        pr_summary: str | None = None,
    ) -> str | None: ...
    async def close(self) -> None: ...
```

- [ ] **Step 4: Refactor `GitHubStateManager.open_review`**

Replace the entire `open_review` method in `agentharness/github_state.py` (lines 454–505) with:

```python
    async def open_review(
        self,
        feature_id: str,
        *,
        pr_title: str | None = None,
        pr_summary: str | None = None,
    ) -> str | None:
        """Open a GitHub pull request for the completed feature.

        When *pr_title* is provided and non-empty, it is used as the PR title;
        otherwise the default ``{feature_id}: implementation complete`` is used.

        When *pr_summary* is provided and non-empty, it forms the PR body
        followed by a separator, ``Closes #N`` (when an issue number exists),
        and the tokens footer. Otherwise the existing log-style body is used.

        Returns the PR URL on success, or None if the PR could not be created.
        """
        state = await self.get(feature_id)

        title = pr_title if pr_title else f"{feature_id}: implementation complete"
        body = self._compose_pr_body(state, pr_summary)

        try:
            default_branch = await self._client.get_default_branch()
            pr = await self._client.create_pull_request(
                title=title,
                body=body,
                head=feature_id,
                base=default_branch,
                labels=[self._feature_marker],
            )
            pr_url = pr.get("html_url")
            if not pr_url:
                log.warning(
                    "PR #%s created but html_url missing in response for feature %s",
                    pr.get("number", "?"),
                    feature_id,
                )
                return None
            log.info("Opened PR #%s for feature %s: %s", pr.get("number", "?"), feature_id, pr_url)
            return pr_url
        except Exception as exc:
            log.error("Could not open PR for %s: %s", feature_id, exc)
            return None

    @staticmethod
    def _build_log_body(state: FeatureState) -> str:
        """Render the existing operational log-style PR body."""
        phases_summary = "\n".join(
            f"- **{phase}**: {info.status.value}"
            for phase, info in state.phases.items()
        )
        tasks_summary = "\n".join(
            f"- {t.task_id}: {t.status.value}"
            for t in state.tasks
        )
        total = state.total_tokens_used()
        tokens_line = str(total.total) if total.total else "unknown"
        closes = f"\nCloses #{state.state_issue_number}\n" if state.state_issue_number else ""
        return (
            f"## Feature: {state.feature_id}\n\n"
            f"### Phases\n{phases_summary}\n\n"
            f"### Tasks\n{tasks_summary}\n\n"
            f"### Tokens used\n{tokens_line}\n\n"
            f"---\n*Generated by AgentHarness*\n"
            f"{closes}"
        )

    @classmethod
    def _compose_pr_body(cls, state: FeatureState, pr_summary: str | None) -> str:
        """Pick between the developer-authored body and the log-style body."""
        if not pr_summary or not pr_summary.strip():
            return cls._build_log_body(state)

        total = state.total_tokens_used()
        tokens_line = str(total.total) if total.total else "unknown"
        closes_block = (
            f"Closes #{state.state_issue_number}\n\n"
            if state.state_issue_number
            else ""
        )
        return (
            f"{pr_summary.rstrip()}\n\n"
            f"---\n\n"
            f"{closes_block}"
            f"### Tokens used\n{tokens_line}\n"
        )
```

- [ ] **Step 5: Run all open_review tests — verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py -v -k open_review`

Expected: All open_review tests pass (the existing two + the six new ones). If existing positional-arg tests fail, see Step 6.

- [ ] **Step 6: Adjust the existing `test_open_review_pr_body_closes_issue` test if it broke**

The pre-existing test at `tests/test_github_state.py:636` uses the old log-style body content. Verify it still passes — the no-kwargs path falls through to `_build_log_body` which preserves the previous shape. If a regex differs, update the assertion accordingly.

Run: `.venv/bin/pytest tests/test_github_state.py -v`

Expected: All passing.

- [ ] **Step 7: Run the broader test suite to confirm Azure backend untouched**

Run: `.venv/bin/pytest tests/test_backend_parity.py -v`

Expected: All passing — `test_azure_state_manager_open_review_returns_none` still passes because the Azure backend has no `open_review` method (the test verifies it returns None when called via the protocol).

- [ ] **Step 8: Commit**

```bash
git add agentharness/storage_protocol.py agentharness/github_state.py tests/test_github_state.py
git commit -m "feat: open_review accepts pr_title and pr_summary kwargs"
```

---

## Task 7: Thread `store` keyword-only kwarg through dispatch chain

**Files:**
- Modify: `agentharness/dispatcher.py` (signatures of `dispatch_after_completion`, `_dispatch_serial_next`, `_dispatch_review_result`, `_open_feature_pr`; body of `_open_feature_pr`)
- Test: `tests/test_dispatcher.py` (update existing `_open_feature_pr` tests to use new signature; existing call sites of `_dispatch_serial_next` / `_dispatch_review_result` / `dispatch_after_completion` continue to work because `store` defaults to `None`)
- Test: `tests/test_dispatcher_github.py` (same)

**Goal:** Add `store: ArtifactStorage | None = None` as a keyword-only optional kwarg to four dispatcher functions, forward it down the chain, and call `_build_pr_content` from `_open_feature_pr` to derive `pr_title` / `pr_summary` before delegating to `state_mgr.open_review`.

- [ ] **Step 1: Write the failing tests for `_open_feature_pr` happy path**

Add to `tests/test_dispatcher.py` (extend the `TestOpenFeaturePr` class — find it near line 920):

```python
class TestOpenFeaturePrWithStore:
    @pytest.mark.asyncio
    async def test_open_feature_pr_passes_title_and_summary_when_store_present(self):
        """_open_feature_pr extracts title+summary and forwards them to open_review."""
        state = FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.done,
            tasks=[
                TaskEntry(
                    task_id="t1",
                    phase="developing",
                    status=TaskStatus.completed,
                    output_artifact="artifacts/feat-x/impl/main.r1.md",
                ),
            ],
        )
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value="https://pr/123")
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Add PR Summary Design\n",
            "artifacts/feat-x/impl/main.r1.md": (
                "## PR Summary\nDeveloper-authored body.\n## Status\nDONE\n"
            ),
        })

        await _open_feature_pr(state, state_mgr, store)

        state_mgr.open_review.assert_awaited_once_with(
            "feat-x",
            pr_title="Add PR Summary Design",
            pr_summary="Developer-authored body.",
        )

    @pytest.mark.asyncio
    async def test_open_feature_pr_passes_none_when_store_missing(self):
        """When store is None, open_review is called with both kwargs as None."""
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.done, tasks=[])
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value=None)

        await _open_feature_pr(state, state_mgr, None)

        state_mgr.open_review.assert_awaited_once_with(
            "feat-x",
            pr_title=None,
            pr_summary=None,
        )

    @pytest.mark.asyncio
    async def test_open_feature_pr_default_store_is_none(self):
        """Default for store kwarg is None when omitted."""
        state = FeatureState(feature_id="feat-y", status=FeatureStatus.done, tasks=[])
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value=None)

        await _open_feature_pr(state, state_mgr)  # store omitted

        state_mgr.open_review.assert_awaited_once_with(
            "feat-y",
            pr_title=None,
            pr_summary=None,
        )
```

> **Note:** The existing tests at line 927 (`test_no_state_mgr_no_op`), 929 (`test_delegates_to_state_mgr_open_review`), and 937 (`test_dispatch_serial_next_calls_open_review`) call `_open_feature_pr(state, state_mgr)` *without* `store`. Once the new keyword passes `pr_title` and `pr_summary` to `open_review`, these existing tests' assertions like `state_mgr.open_review.assert_awaited_once_with("feat-auth")` will fail because the call now uses kwargs. We update them in Step 4.

- [ ] **Step 2: Run tests — verify the 3 new tests fail**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestOpenFeaturePrWithStore -v`

Expected: 3 failures — `_open_feature_pr` does not yet accept the new arguments; or the assertion against kwargs differs.

- [ ] **Step 3: Update dispatcher signatures and `_open_feature_pr` body**

Edit `agentharness/dispatcher.py`:

(a) Update `dispatch_after_completion` signature (around line 104):

```python
async def dispatch_after_completion(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState | None:
```

(b) Forward `store` from `dispatch_after_completion` to the two child dispatchers (around lines 144 and 147):

```python
    if status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        return await _dispatch_serial_next(
            state, completed_task, agent_output, config, queues, state_mgr, store=store
        )

    if status == FeatureStatus.reviewing:
        return await _dispatch_review_result(
            state, completed_task, agent_output, config, queues, state_mgr, store=store
        )
```

(c) Update `_dispatch_serial_next` signature and body (around line 345):

```python
async def _dispatch_serial_next(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState:
    dev_status = _parse_developer_status(agent_output)
    if dev_status in ("BLOCKED", "NEEDS_CONTEXT"):
        log.warning(
            "Dev task %s reported %s — marking feature failed",
            completed_task.task_id,
            dev_status,
        )
        return state.with_status(FeatureStatus.failed).with_event(
            "feature_failed", details=f"Task {completed_task.task_id} reported {dev_status}"
        )
    log.info(
        "Dev task %s complete (%s) — in-developer review already done, marking feature done",
        completed_task.task_id,
        dev_status,
    )
    done_state = state.with_status(FeatureStatus.done).with_event("feature_completed")
    await _open_feature_pr(done_state, state_mgr, store)
    return done_state
```

(d) Update `_dispatch_review_result` signature and PR-open call (around line 412):

```python
async def _dispatch_review_result(
    state: FeatureState,
    completed_task: TaskMessage,
    review_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState:
    task_name = completed_task.context or _task_name_from_id(completed_task.task_id, state.feature_id)
    failed_tasks = _parse_review_result(review_output)

    if task_name not in failed_tasks:
        next_task_entry = state.next_pending_task("developing")
        if next_task_entry is None:
            log.info("All tasks reviewed and passed for %s — done", state.feature_id)
            done_state = state.with_status(FeatureStatus.done).with_event("feature_completed")
            await _open_feature_pr(done_state, state_mgr, store)
            return done_state
        # ... rest unchanged
```

> The remainder of `_dispatch_review_result` is unchanged. The only edit is adding `*, store=None` to the signature and `store` to the `_open_feature_pr` call.

(e) Replace `_open_feature_pr` (around line 733) with:

```python
async def _open_feature_pr(
    state: FeatureState,
    state_mgr: StateBackend | None,
    store: ArtifactStorage | None = None,
) -> None:
    """Open a GitHub PR for the completed feature via the state backend.

    Builds (pr_title, pr_summary) from the brief and last developer impl
    artifact when a store is available; otherwise passes (None, None) so the
    backend falls back to the log-style PR content.
    """
    if state_mgr is None:
        return
    pr_title, pr_summary = await _build_pr_content(state, store)
    await state_mgr.open_review(
        state.feature_id,
        pr_title=pr_title,
        pr_summary=pr_summary,
    )
```

- [ ] **Step 4: Update existing `_open_feature_pr` and dispatch tests for the new keyword call shape**

In `tests/test_dispatcher.py`:

Find the existing `TestOpenFeaturePr` class block near line 920. Update assertions:

```python
# Before
state_mgr.open_review.assert_awaited_once_with("feat-auth")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-auth", pr_title=None, pr_summary=None,
)
```

```python
# Before (line ~948)
state_mgr.open_review.assert_awaited_once_with("feat-gh")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-gh", pr_title=None, pr_summary=None,
)
```

In the existing `_dispatch_review_result` "all-pass" test near line 456:

```python
# Before
state_mgr.open_review.assert_awaited_once_with("feat-3")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-3", pr_title=None, pr_summary=None,
)
```

In `tests/test_dispatcher.py` near line 504 (`test_pass_with_no_more_tasks_calls_open_review`):

```python
# Before
state_mgr.open_review.assert_awaited_once_with("feat-3")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-3", pr_title=None, pr_summary=None,
)
```

In `tests/test_dispatcher_github.py` lines 51, 64:

```python
# Before
state_mgr.open_review.assert_awaited_once_with("feat-pr-test")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-pr-test", pr_title=None, pr_summary=None,
)
```

```python
# Before
state_mgr.open_review.assert_awaited_once_with("feat-delegate")
# After
state_mgr.open_review.assert_awaited_once_with(
    "feat-delegate", pr_title=None, pr_summary=None,
)
```

> **Why these match:** every existing call to `_open_feature_pr` in tests omits `store`, so it defaults to `None`. `_build_pr_content` returns `(None, None)` when store is None. So the new assertion shape is exactly the no-op fallback path.

- [ ] **Step 5: Run the full dispatcher test suite**

Run: `.venv/bin/pytest tests/test_dispatcher.py tests/test_dispatcher_github.py -v`

Expected: All passing — including the 3 new tests from Step 1 and the updated existing assertions.

- [ ] **Step 6: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py tests/test_dispatcher_github.py
git commit -m "feat: thread artifact store through dispatch chain to PR open"
```

---

## Task 8: Wire `store=store` from `run_task.py`

**Files:**
- Modify: `agentharness/run_task.py` (line 128)
- Test: `tests/test_run_task.py` (no changes required — existing `dispatch_after_completion` is already mocked)

**Goal:** Pass the in-scope `store` instance into `dispatch_after_completion`. This is a one-line change.

- [ ] **Step 1: Verify the existing call site**

Read `agentharness/run_task.py` line 128. Current line:

```python
        next_state = await dispatch_after_completion(updated_state, task, result.output, config, all_queues, state_mgr)
```

`store` is constructed at line 77 and is in scope here.

- [ ] **Step 2: Add `store=store` to the call**

Replace line 128 in `agentharness/run_task.py`:

```python
        next_state = await dispatch_after_completion(
            updated_state, task, result.output, config, all_queues, state_mgr, store=store,
        )
```

- [ ] **Step 3: Run the run_task tests**

Run: `.venv/bin/pytest tests/test_run_task.py -v`

Expected: All passing — the existing tests mock `dispatch_after_completion`, so the new kwarg is accepted transparently. If any test asserts the exact call signature, update it to include `store=mock_store`.

- [ ] **Step 4: Run the full test suite as a smoke pass**

Run: `.venv/bin/pytest -x --ff -q`

Expected: All passing.

- [ ] **Step 5: Commit**

```bash
git add agentharness/run_task.py tests/test_run_task.py
git commit -m "feat: pass artifact store from run_task into dispatch chain"
```

---

## Task 9: Delete dead `_build_pr_body` helper in dispatcher.py

**Files:**
- Modify: `agentharness/dispatcher.py` (lines ~610–634 — delete the entire `_build_pr_body` function)

**Why:** The `_build_pr_body` helper at `agentharness/dispatcher.py:610` is unused. The actual PR body assembly lives inside `GitHubStateManager.open_review`. Keeping two divergent copies invites drift; we keep one canonical implementation in `github_state.py`.

- [ ] **Step 1: Confirm the helper is unused**

Run: `grep -n "_build_pr_body" agentharness/ tests/ -R`

Expected: Only the definition at `dispatcher.py` and the local closure inside `github_state.py:open_review` (which is *not* the same function — it's a nested helper using the module-private name). Since the dispatcher version has no callers, deleting it is safe.

If the grep shows other callers, stop and investigate. Otherwise proceed.

- [ ] **Step 2: Delete the function from `dispatcher.py`**

Remove these lines from `agentharness/dispatcher.py` (the entire `_build_pr_body` function — currently lines 610–634):

```python
def _build_pr_body(state: FeatureState) -> str:
    phases_summary = "\n".join(
        f"- **{phase}**: {info.status.value}"
        for phase, info in state.phases.items()
    )
    tasks_summary = "\n".join(
        f"- {t.task_id}: {t.status.value}"
        for t in state.tasks
    )
    total = state.total_tokens_used()
    tokens_line = str(total.total) if total.total else "unknown"
    return f"""## Feature: {state.feature_id}

### Phases
{phases_summary}

### Tasks
{tasks_summary}

### Tokens used
{tokens_line}

---
*Generated by AgentHarness*
"""
```

- [ ] **Step 3: Run the full test suite**

Run: `.venv/bin/pytest -q`

Expected: All passing — nothing imports `dispatcher._build_pr_body`.

- [ ] **Step 4: Commit**

```bash
git add agentharness/dispatcher.py
git commit -m "refactor: remove unused _build_pr_body helper from dispatcher"
```

---

## Final verification

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest -v`

Expected: All passing. If the project has a coverage gate, run:

`.venv/bin/pytest --cov=agentharness --cov-report=term-missing`

Expected: Coverage on `dispatcher.py` and `github_state.py` ≥ 80% — the new helpers are fully covered by tests.

- [ ] **Step 2: Smoke-run the harness on a sample feature** *(if a local pipeline is available)*

If you have a running feature pipeline that just completed, inspect the resulting GitHub PR:
- Title should match the brief's `# Heading` (or fall back to `{feature_id}: implementation complete`).
- Body should start with the developer's `## PR Summary` content followed by `---`, `Closes #N`, and the tokens footer.
- If artifacts are missing, the body should be the original log-style content unchanged.

If no pipeline is available, skip — unit tests cover all paths.

- [ ] **Step 3: Push to remote**

```bash
git push
```

---

## Self-review checklist

**Spec coverage** (FR-1 through FR-9 + NFR-1 through NFR-4):

- ✅ FR-1: `## PR Summary` section in developer prompt — Task 1
- ✅ FR-2: `_extract_brief_title` — Task 2
- ✅ FR-3: `_extract_pr_summary` — Task 3
- ✅ FR-4: `_last_developer_artifact` — Task 4
- ✅ FR-5: `store` threaded through dispatch chain — Tasks 7 + 8
- ✅ FR-6: `_open_feature_pr` assembly + downloads + exception swallowing — Tasks 5 + 7
- ✅ FR-7: `open_review` signature + body branching — Task 6
- ✅ FR-8: Protocol update — Task 6
- ✅ FR-9: Graceful fallback — Tasks 5, 6, 7 (test cases for every fallback path)
- ✅ NFR-1: Performance — at most 2 downloads, no agent calls
- ✅ NFR-2: Security — no sanitization, GitHub renders safely
- ✅ NFR-3: Backwards compatibility — all kwargs default to `None`
- ✅ NFR-4: Observability — INFO logs in `_build_pr_content`, ERROR + stack on unexpected exception

**Spec amendments from arch-review** (1–5):

- ✅ Amendment 1: Token-count footer separator (`\n\n---\n\n`) — Task 6 `_compose_pr_body`
- ✅ Amendment 2: `_extract_pr_summary` returns None for empty `### Changes` — Task 3
- ✅ Amendment 3: INFO logs for fallbacks, `log.exception` for unexpected — Task 5
- ✅ Amendment 4: Concrete prompt example with header + paragraphs + 2–3 backtick-fenced paths — Task 1
- ✅ Amendment 5: Delete dead `_build_pr_body` — Task 9

**Type / signature consistency:**

- ✅ `_extract_brief_title(content: str) -> str` — used identically in Tasks 2 and 5
- ✅ `_extract_pr_summary(impl_content: str) -> str | None` — used identically in Tasks 3 and 5
- ✅ `_last_developer_artifact(state: FeatureState) -> str | None` — used identically in Tasks 4 and 5
- ✅ `_build_pr_content(state, store) -> tuple[str | None, str | None]` — used identically in Tasks 5 and 7
- ✅ `open_review(self, feature_id, *, pr_title=None, pr_summary=None)` — identical signature in Tasks 6 (protocol) and 6 (impl) and 7 (call site)
- ✅ `dispatch_after_completion(..., *, store=None)` — identical in Tasks 7 and 8
- ✅ `_open_feature_pr(state, state_mgr, store=None)` — identical in Tasks 5/7 calls and definition

**Placeholder scan:**

No `TBD`, `TODO`, `implement later`, `Add appropriate error handling`, `handle edge cases`, or `Similar to Task N` strings in the plan. Every code step has complete code.
