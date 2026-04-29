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
async def test_list_features_skips_issues_without_parseable_state():
    # Arrange
    state = _make_state()
    good_issue = _make_issue(state, number=5)
    # Issue with TEST_FEATURE_MARKER but no parseable state JSON
    bad_issue = {
        "number": 6,
        "body": "",
        "labels": [{"name": TEST_FEATURE_MARKER}],
    }
    client = _mock_client()
    client.list_issues.return_value = [good_issue, bad_issue]
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    results = await mgr.list_features()

    # Assert — bad_issue silently skipped
    assert len(results) == 1
    assert results[0].feature_id == state.feature_id


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
