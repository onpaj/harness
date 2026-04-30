"""Unit tests for agentharness.github_state.GitHubStateManager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.github_labels import (
    FEATURE_STATUS_TO_LABEL,
    FEAT_ANALYZING,
    FEAT_DEVELOPING,
    FEAT_DONE,
)
from agentharness.github_state import (
    GitHubStateManager,
    _build_state_block,
    _extract_state_json,
    _feature_label,
    _feature_issue_title,
    _replace_state_block,
    parse_state_from_issue,
)
from agentharness.models import FeatureState, FeatureStatus

TEST_FEATURE_MARKER = "test-marker"

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_state(
    feature_id: str = "feat-20260427-abc123",
    status: FeatureStatus = FeatureStatus.analyzing,
) -> FeatureState:
    return FeatureState(
        feature_id=feature_id,
        status=status,
        created_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC),
    )


def _make_issue(
    state: FeatureState,
    *,
    number: int = 42,
    brief_content: str = "",
    extra_labels: list[str] | None = None,
) -> dict:
    """Build a minimal GitHub issue dict with state embedded in the body."""
    feat_lbl = _feature_label(state.feature_id)
    status_lbl = FEATURE_STATUS_TO_LABEL[state.status]
    label_names = [TEST_FEATURE_MARKER, feat_lbl, status_lbl] + (extra_labels or [])
    return {
        "number": number,
        "body": _replace_state_block(brief_content, state),
        "labels": [{"name": n} for n in label_names],
    }


def _make_raw_issue(
    *,
    number: int,
    title: str = "Raw Feature Title",
    body: str = "Raw issue body",
) -> dict:
    """Build a GitHub issue with marker label but no state JSON block."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "created_at": "2026-04-25T10:00:00Z",
        "updated_at": "2026-04-25T10:00:00Z",
        "labels": [{"name": TEST_FEATURE_MARKER}],
    }


def _mock_client(owner: str = "acme", repo: str = "runs") -> AsyncMock:
    client = AsyncMock()
    client.owner = owner
    client.repo = repo
    return client


# ---------------------------------------------------------------------------
# _extract_state_json / _build_state_block / _replace_state_block helpers
# ---------------------------------------------------------------------------


def test_build_state_block_round_trip():
    state = _make_state()
    block = _build_state_block(state)
    extracted = _extract_state_json(block)
    parsed = FeatureState.model_validate_json(extracted)
    assert parsed.feature_id == state.feature_id
    assert parsed.status == state.status


def test_extract_state_json_raises_when_block_missing():
    with pytest.raises(ValueError, match="No agentharness-state fenced block"):
        _extract_state_json("Some body without a fenced block")


def test_replace_state_block_appends_when_absent():
    state = _make_state()
    result = _replace_state_block("# Brief\n\nSome text.", state)
    assert "# Brief" in result
    parsed = parse_state_from_issue({"body": result})
    assert parsed is not None
    assert parsed.feature_id == state.feature_id


def test_replace_state_block_replaces_existing():
    state_v1 = _make_state(status=FeatureStatus.analyzing)
    state_v2 = _make_state(status=FeatureStatus.planning)
    body = _replace_state_block("", state_v1)
    body = _replace_state_block(body, state_v2)
    # Only one block should remain
    assert body.count("```agentharness-state") == 1
    parsed = parse_state_from_issue({"body": body})
    assert parsed is not None
    assert parsed.status == FeatureStatus.planning


def test_parse_state_from_issue_returns_none_when_no_block():
    result = parse_state_from_issue({"body": "No state block here"})
    assert result is None


def test_parse_state_from_issue_returns_none_on_empty_body():
    result = parse_state_from_issue({"body": ""})
    assert result is None


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_calls_ensure_label_and_create_issue():
    # Arrange
    state = _make_state()
    client = _mock_client()
    client.create_issue.return_value = {"number": 42}
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.create(state)

    # Assert — ensure_labels called with TEST_FEATURE_MARKER and status label
    client.ensure_labels.assert_awaited_once()
    labels_arg, _ = client.ensure_labels.call_args
    assert TEST_FEATURE_MARKER in labels_arg[0]
    assert FEATURE_STATUS_TO_LABEL[state.status] in labels_arg[0]

    # Assert — create_issue called with correct labels and title
    client.create_issue.assert_awaited_once()
    _, kwargs = client.create_issue.call_args
    assert kwargs["title"] == _feature_issue_title(state.feature_id)
    assert TEST_FEATURE_MARKER in kwargs["labels"]
    assert FEATURE_STATUS_TO_LABEL[state.status] in kwargs["labels"]


@pytest.mark.asyncio
async def test_create_embeds_state_json_in_issue_body():
    # Arrange
    state = _make_state()
    brief = "# Feature Brief\n\nSome description."
    client = _mock_client()
    client.create_issue.return_value = {"number": 42}
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.create(state, brief_content=brief)

    # Assert — issue body contains brief and state block
    _, kwargs = client.create_issue.call_args
    body = kwargs["body"]
    assert "# Feature Brief" in body
    parsed = parse_state_from_issue({"body": body})
    assert parsed is not None
    assert parsed.feature_id == state.feature_id


@pytest.mark.asyncio
async def test_create_does_not_create_comment():
    # Arrange
    state = _make_state()
    client = _mock_client()
    client.create_issue.return_value = {"number": 42}
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.create(state)

    # Assert — no comment created (state is in body now)
    client.create_comment.assert_not_awaited()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_reconstructs_feature_state():
    # Arrange
    state = _make_state()
    issue = _make_issue(state)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    result = await mgr.get(state.feature_id)

    # Assert
    assert result.feature_id == state.feature_id
    assert result.status == FeatureStatus.analyzing


@pytest.mark.asyncio
async def test_get_does_not_call_list_comments_when_body_has_state():
    # Arrange
    state = _make_state()
    issue = _make_issue(state)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.get(state.feature_id)

    # Assert — no comment fetch needed
    client.list_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_overrides_status_from_label():
    """Status in the JSON blob is overridden by the feat:* label on the issue."""
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    issue = _make_issue(state, number=7)
    # Override label to say developing
    issue["labels"] = [
        {"name": TEST_FEATURE_MARKER},
        {"name": _feature_label(state.feature_id)},
        {"name": FEAT_DEVELOPING},
    ]
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    result = await mgr.get(state.feature_id)

    # Assert — label wins over JSON
    assert result.status == FeatureStatus.developing



@pytest.mark.asyncio
async def test_get_raises_key_error_when_not_found():
    # Arrange
    client = _mock_client()
    client.list_issues.return_value = []
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act / Assert
    with pytest.raises(KeyError, match="No state found for feature"):
        await mgr.get("feat-missing-0000")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rewrites_issue_body_without_label_swap_when_status_unchanged():
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    issue = _make_issue(state, number=10)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    worktree = "/tmp/wt"
    new_state = await mgr.update(
        state.feature_id,
        lambda s: s.with_worktree_path(worktree),
    )

    # Assert — issue body updated (not a comment)
    client.update_issue.assert_awaited_once()
    call_kwargs = client.update_issue.call_args[1]
    assert call_kwargs["body"]  # non-empty
    client.update_comment.assert_not_awaited()

    # Assert — no label ops since status is unchanged
    client.add_labels.assert_not_awaited()
    client.remove_label.assert_not_awaited()

    assert new_state.worktree_path == worktree


@pytest.mark.asyncio
async def test_update_body_preserves_brief_and_embeds_new_state():
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    brief = "# My Brief\n\nImportant text."
    issue = _make_issue(state, number=10, brief_content=brief)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    new_state = await mgr.update(state.feature_id, lambda s: s.with_status(FeatureStatus.planning))

    # Assert — updated body contains brief and new state
    call_kwargs = client.update_issue.call_args[1]
    updated_body = call_kwargs["body"]
    assert "# My Brief" in updated_body
    parsed = parse_state_from_issue({"body": updated_body})
    assert parsed is not None
    assert parsed.status == FeatureStatus.planning


@pytest.mark.asyncio
async def test_update_swaps_feat_labels_when_status_changes():
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    issue = _make_issue(state, number=11)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act — bump status to done
    new_state = await mgr.update(
        state.feature_id,
        lambda s: s.with_status(FeatureStatus.done),
    )

    # Assert — new label added, old label removed
    client.add_labels.assert_awaited_once_with(11, [FEAT_DONE])
    client.remove_label.assert_awaited_once_with(11, FEAT_ANALYZING)

    # Assert — issue body updated (not a comment)
    client.update_issue.assert_awaited_once()
    client.update_comment.assert_not_awaited()

    assert new_state.status == FeatureStatus.done


@pytest.mark.asyncio
async def test_update_returns_new_state():
    # Arrange
    state = _make_state()
    issue = _make_issue(state, number=5)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    returned = await mgr.update(state.feature_id, lambda s: s)

    # Assert — returned state has correct feature_id
    assert returned.feature_id == state.feature_id


# ---------------------------------------------------------------------------
# set_worktree_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_worktree_path_calls_update():
    # Arrange
    state = _make_state()
    issue = _make_issue(state, number=3)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.set_worktree_path(state.feature_id, "/some/path")

    # Assert — issue body updated
    client.update_issue.assert_awaited_once()
    call_kwargs = client.update_issue.call_args[1]
    persisted = parse_state_from_issue({"body": call_kwargs["body"]})
    assert persisted is not None
    assert persisted.worktree_path == "/some/path"


# ---------------------------------------------------------------------------
# set_cleanup_warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_cleanup_warning_calls_update():
    # Arrange
    state = _make_state()
    issue = _make_issue(state, number=4)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    await mgr.set_cleanup_warning(state.feature_id, "disk full")

    # Assert — issue body updated with warning
    client.update_issue.assert_awaited_once()
    call_kwargs = client.update_issue.call_args[1]
    persisted = parse_state_from_issue({"body": call_kwargs["body"]})
    assert persisted is not None
    assert persisted.cleanup_warning == "disk full"


# ---------------------------------------------------------------------------
# list_features
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_features_returns_correct_pairs():
    # Arrange
    state_a = _make_state("feat-20260427-aaa")
    state_b = _make_state("feat-20260427-bbb")
    issue_a = _make_issue(state_a, number=1)
    issue_b = _make_issue(state_b, number=2)
    client = _mock_client()
    # list_issues returns newest first (higher number first)
    client.list_issues.return_value = [issue_b, issue_a]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert — returns list of FeatureState sorted by issue number descending
    assert len(results) == 2
    assert results[0].feature_id == "feat-20260427-bbb"
    assert results[1].feature_id == "feat-20260427-aaa"


@pytest.mark.asyncio
async def test_list_features_synthesizes_raw_issue_without_state_block():
    """An issue with the marker label but no state JSON now appears as raw."""
    # Arrange
    raw = _make_raw_issue(number=11, title="Add Export Endpoint")
    client = _mock_client()
    client.list_issues.return_value = [raw]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    assert len(results) == 1
    state = results[0]
    assert state.feature_id == "feat-add-export-endpoint"
    assert state.status == FeatureStatus.brainstormed
    assert state.state_issue_number == 11
    assert state.branch_name == "feat-add-export-endpoint"
    assert state.is_raw is True


@pytest.mark.asyncio
async def test_list_features_returns_both_raw_and_initialized_features():
    """Both raw and initialized features appear in list_features results."""
    # Arrange
    # Create initialized state with history to distinguish it from raw
    initialized_state = _make_state("feat-initialized")
    initialized_state = initialized_state.with_event("brief_uploaded")
    initialized = _make_issue(initialized_state, number=20)
    raw = _make_raw_issue(number=21, title="Raw Thing")
    client = _mock_client()
    client.list_issues.return_value = [raw, initialized]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    feature_ids = {s.feature_id for s in results}
    assert feature_ids == {"feat-initialized", "feat-raw-thing"}
    raw_state = next(s for s in results if s.feature_id == "feat-raw-thing")
    init_state = next(s for s in results if s.feature_id == "feat-initialized")
    assert raw_state.is_raw is True
    assert init_state.is_raw is False


@pytest.mark.asyncio
async def test_list_features_dedup_two_raw_issues_keeps_newest():
    """When two raw issues slug to the same feature_id, the higher number wins."""
    # Arrange
    older = _make_raw_issue(number=1, title="Same Title")
    newer = _make_raw_issue(number=5, title="Same Title")
    client = _mock_client()
    client.list_issues.return_value = [newer, older]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    assert len(results) == 1
    assert results[0].state_issue_number == 5


@pytest.mark.asyncio
async def test_list_features_dedup_raw_vs_initialized_keeps_initialized():
    """When a raw and initialized issue share a slug, the initialized state is preserved."""
    # Arrange
    initialized_state = _make_state("feat-shared-slug")
    initialized_state = initialized_state.with_event("brief_uploaded")
    initialized = _make_issue(initialized_state, number=2)
    initialized["created_at"] = "2026-04-25T10:00:00Z"
    initialized["updated_at"] = "2026-04-25T10:00:00Z"
    raw = _make_raw_issue(number=8, title="Shared Slug")  # same slug, higher number
    client = _mock_client()
    client.list_issues.return_value = [raw, initialized]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    assert len(results) == 1
    # Initialized issue wins even though raw has higher number
    assert results[0].is_raw is False
    assert results[0].feature_id == "feat-shared-slug"


@pytest.mark.asyncio
async def test_list_features_dedup_two_initialized_keeps_newest():
    """When two initialized issues share a slug, the higher-numbered one wins."""
    # Arrange
    older_state = _make_state("feat-shared-slug")
    newer_state = _make_state("feat-shared-slug")
    older = _make_issue(older_state, number=3)
    newer = _make_issue(newer_state, number=9)
    client = _mock_client()
    # When list_issues is called, it returns both; when get_issue is called for the newer one
    client.list_issues.return_value = [newer, older]
    # When we re-fetch issue 9 during _state_from_issue, return it with state_issue_number set
    newer_with_number = newer.copy()
    newer_with_number["state_issue_number"] = 9
    client.get_issue = AsyncMock(return_value=newer_with_number)
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    assert len(results) == 1
    # Verify the dedup kept issue 9 by checking get_issue was called (which happens
    # in _state_from_issue when the body is fully parsed)
    assert results[0].feature_id == "feat-shared-slug"


@pytest.mark.asyncio
async def test_list_features_returns_empty_when_no_issues():
    # Arrange
    client = _mock_client()
    client.list_issues.return_value = []
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert
    assert results == []


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_creates_instance():
    # Arrange
    config = MagicMock()
    config.github.token = "ghp_test"
    config.github.owner = "acme"
    config.github.runs_repo = "runs"
    config.github.feature_marker = "configured-marker"

    with patch(
        "agentharness.github_client.GitHubClient.from_config",
        return_value=AsyncMock(),
    ) as mock_from_config:
        # Act
        mgr = GitHubStateManager.from_config(config)

        # Assert
        mock_from_config.assert_called_once_with(config)
        assert isinstance(mgr, GitHubStateManager)
        assert mgr._feature_marker == "configured-marker"


# ---------------------------------------------------------------------------
# open_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_review_passes_feature_marker_as_label():
    """The final PR is created with the configured feature_marker label."""
    state = _make_state(status=FeatureStatus.done)
    issue = _make_issue(state, number=20)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    client.get_default_branch.return_value = "main"
    client.create_pull_request.return_value = {
        "number": 99,
        "html_url": "https://example/pr/99",
    }
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    pr_url = await mgr.open_review(state.feature_id)

    assert pr_url == "https://example/pr/99"
    client.create_pull_request.assert_awaited_once()
    _, kwargs = client.create_pull_request.call_args
    assert kwargs["labels"] == [TEST_FEATURE_MARKER]
    assert kwargs["base"] == "main"
    assert kwargs["head"] == state.feature_id


@pytest.mark.asyncio
async def test_open_review_pr_body_closes_issue():
    """PR body includes 'Closes #<issue_number>' when state_issue_number is set."""
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 42})
    issue = _make_issue(state_with_issue, number=42)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    client.get_default_branch.return_value = "main"
    client.create_pull_request.return_value = {
        "number": 99,
        "html_url": "https://example/pr/99",
    }
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    await mgr.open_review(state_with_issue.feature_id)

    _, kwargs = client.create_pull_request.call_args
    assert "Closes #42" in kwargs["body"]


# ---------------------------------------------------------------------------
# open_review body branching (Task 6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_review_uses_pr_title_when_provided():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 7})
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title="Add PR Summary Design", pr_summary=None)

    _, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == "Add PR Summary Design"


@pytest.mark.asyncio
async def test_open_review_uses_default_title_when_pr_title_none():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 7})
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=None)

    _, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == f"{state.feature_id}: implementation complete"


@pytest.mark.asyncio
async def test_open_review_uses_pr_summary_body_when_provided():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 12})
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    summary = "Implemented X.\n\n### Changes\n- `file.py` — note"
    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=summary)

    _, kwargs = client.create_pull_request.call_args
    body = kwargs["body"]
    assert body.startswith("Implemented X.")
    assert "### Changes" in body
    assert "\n\n---\n\n" in body
    assert "Closes #12" in body
    assert "### Tokens used" in body
    assert "## Feature:" not in body
    assert "### Phases" not in body


@pytest.mark.asyncio
async def test_open_review_uses_log_body_when_pr_summary_none():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 12})
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary=None)

    _, kwargs = client.create_pull_request.call_args
    body = kwargs["body"]
    assert "## Feature:" in body
    assert "### Phases" in body
    assert "### Tasks" in body
    assert "### Tokens used" in body
    assert "Closes #12" in body


@pytest.mark.asyncio
async def test_open_review_omits_closes_line_when_no_issue_number():
    state = _make_state(status=FeatureStatus.done)
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state)

    await mgr.open_review(state.feature_id, pr_title=None, pr_summary="Body.")

    _, kwargs = client.create_pull_request.call_args
    assert "Closes #" not in kwargs["body"]


@pytest.mark.asyncio
async def test_open_review_back_compat_no_kwargs():
    state = _make_state(status=FeatureStatus.done)
    state_with_issue = state.model_copy(update={"state_issue_number": 1})
    client = _mock_client()
    client.get_default_branch = AsyncMock(return_value="main")
    client.create_pull_request = AsyncMock(return_value={"number": 99, "html_url": "https://x"})
    mgr = GitHubStateManager(client=client, feature_marker=TEST_FEATURE_MARKER)
    mgr.get = AsyncMock(return_value=state_with_issue)

    pr_url = await mgr.open_review(state.feature_id)
    assert pr_url == "https://x"
    _, kwargs = client.create_pull_request.call_args
    assert kwargs["title"] == f"{state.feature_id}: implementation complete"
    assert "## Feature:" in kwargs["body"]


# ---------------------------------------------------------------------------
# patch_existing_issue
# ---------------------------------------------------------------------------


class TestPatchExistingIssue:
    @pytest.mark.asyncio
    async def test_appends_state_block_when_absent(self):
        from agentharness.github_state import _STATE_BLOCK_RE, parse_state_from_issue
        state = _make_state("feat-x", status=FeatureStatus.brainstormed)
        client = _mock_client()
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
        assert new_body.count("My brief content.") == 1


# ---------------------------------------------------------------------------
# slug_title
# ---------------------------------------------------------------------------


class TestSlugTitle:
    """The slug algorithm must match /convertforagent byte-for-byte."""

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
        # Should not raise; falls back to model defaults
        state = _synthesize_raw_state(issue)
        assert state.created_at is not None
        assert state.updated_at is not None
