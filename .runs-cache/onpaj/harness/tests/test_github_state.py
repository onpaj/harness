"""Unit tests for agentharness.github_state.GitHubStateManager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentharness.github_labels import (
    FEATURE_MARKER,
    FEATURE_STATUS_TO_LABEL,
    FEAT_ANALYZING,
    FEAT_DEVELOPING,
    FEAT_DONE,
)
from agentharness.github_state import (
    GitHubStateManager,
    _build_body,
    _extract_state_json,
    _feature_label,
)
from agentharness.models import FeatureState, FeatureStatus


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
    extra_labels: list[str] | None = None,
) -> dict:
    """Build a minimal GitHub issue dict from a FeatureState."""
    feat_lbl = _feature_label(state.feature_id)
    status_lbl = FEATURE_STATUS_TO_LABEL[state.status]
    label_names = [FEATURE_MARKER, feat_lbl, status_lbl] + (extra_labels or [])
    return {
        "number": number,
        "body": _build_body(state),
        "labels": [{"name": n} for n in label_names],
    }


def _mock_client(owner: str = "acme", repo: str = "runs") -> AsyncMock:
    client = AsyncMock()
    client.owner = owner
    client.repo = repo
    return client


# ---------------------------------------------------------------------------
# _extract_state_json / _build_body helpers
# ---------------------------------------------------------------------------


def test_build_body_round_trip():
    state = _make_state()
    body = _build_body(state)
    extracted = _extract_state_json(body)
    parsed = FeatureState.model_validate_json(extracted)
    assert parsed.feature_id == state.feature_id
    assert parsed.status == state.status


def test_extract_state_json_raises_when_block_missing():
    with pytest.raises(ValueError, match="No agentharness-state fenced block"):
        _extract_state_json("Some body without a fenced block")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_calls_ensure_label_and_create_issue():
    # Arrange
    state = _make_state()
    client = _mock_client()
    mgr = GitHubStateManager(client)

    # Act
    await mgr.create(state)

    # Assert — ensure_label called with feature-specific label
    client.ensure_label.assert_awaited_once_with(
        _feature_label(state.feature_id), color="0075ca"
    )

    # Assert — create_issue called with correct labels
    client.create_issue.assert_awaited_once()
    _, kwargs = client.create_issue.call_args
    assert kwargs["title"] == state.feature_id
    assert FEATURE_MARKER in kwargs["labels"]
    assert _feature_label(state.feature_id) in kwargs["labels"]
    assert FEATURE_STATUS_TO_LABEL[state.status] in kwargs["labels"]


@pytest.mark.asyncio
async def test_create_body_contains_fenced_block():
    # Arrange
    state = _make_state()
    client = _mock_client()
    mgr = GitHubStateManager(client)

    # Act
    await mgr.create(state)

    # Assert — body contains parseable state JSON
    _, kwargs = client.create_issue.call_args
    body = kwargs["body"]
    extracted = _extract_state_json(body)
    parsed = FeatureState.model_validate_json(extracted)
    assert parsed.feature_id == state.feature_id


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_reconstructs_feature_state():
    # Arrange
    state = _make_state()
    issue = _make_issue(state)
    client = _mock_client()
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    # Act
    result = await mgr.get(state.feature_id)

    # Assert
    assert result.feature_id == state.feature_id
    assert result.status == FeatureStatus.analyzing


@pytest.mark.asyncio
async def test_get_overrides_status_from_label():
    """Status in the JSON blob is overridden by the feat:* label on the issue."""
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    # Build issue body that claims "analyzing" in the JSON…
    body_with_stale_json = _build_body(state)
    # …but the issue label says "developing"
    issue = {
        "number": 7,
        "body": body_with_stale_json,
        "labels": [
            {"name": FEATURE_MARKER},
            {"name": _feature_label(state.feature_id)},
            {"name": FEAT_DEVELOPING},  # label is authoritative
        ],
    }
    client = _mock_client()
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    # Act
    result = await mgr.get(state.feature_id)

    # Assert — label wins over JSON
    assert result.status == FeatureStatus.developing


@pytest.mark.asyncio
async def test_get_raises_key_error_when_not_found():
    # Arrange
    client = _mock_client()
    client.search_issues.return_value = []
    mgr = GitHubStateManager(client)

    # Act / Assert
    with pytest.raises(KeyError, match="No state found for feature"):
        await mgr.get("feat-missing-0000")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rewrites_body_without_label_swap_when_status_unchanged():
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    issue = _make_issue(state, number=10)
    client = _mock_client()
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    worktree = "/tmp/wt"
    new_state = await mgr.update(
        state.feature_id,
        lambda s: s.with_worktree_path(worktree),
    )

    # Assert — body rewritten
    client.update_issue.assert_awaited_once()
    call_number, call_kwargs = client.update_issue.call_args
    assert "body" in call_kwargs

    # Assert — no label ops since status is unchanged
    client.add_labels.assert_not_awaited()
    client.remove_label.assert_not_awaited()

    assert new_state.worktree_path == worktree


@pytest.mark.asyncio
async def test_update_swaps_feat_labels_when_status_changes():
    # Arrange
    state = _make_state(status=FeatureStatus.analyzing)
    issue = _make_issue(state, number=11)
    client = _mock_client()
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    # Act — bump status to done
    new_state = await mgr.update(
        state.feature_id,
        lambda s: s.with_status(FeatureStatus.done),
    )

    # Assert — new label added, old label removed
    client.add_labels.assert_awaited_once_with(11, [FEAT_DONE])
    client.remove_label.assert_awaited_once_with(11, FEAT_ANALYZING)

    # Assert — body rewritten
    client.update_issue.assert_awaited_once()

    assert new_state.status == FeatureStatus.done


@pytest.mark.asyncio
async def test_update_returns_new_state():
    # Arrange
    state = _make_state()
    issue = _make_issue(state, number=5)
    client = _mock_client()
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

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
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    # Act
    await mgr.set_worktree_path(state.feature_id, "/some/path")

    # Assert — update_issue was called (body was rewritten)
    client.update_issue.assert_awaited_once()
    _, call_kwargs = client.update_issue.call_args
    new_body = call_kwargs["body"]
    persisted_json = _extract_state_json(new_body)
    persisted = FeatureState.model_validate_json(persisted_json)
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
    client.search_issues.return_value = [issue]
    mgr = GitHubStateManager(client)

    # Act
    await mgr.set_cleanup_warning(state.feature_id, "disk full")

    # Assert
    client.update_issue.assert_awaited_once()
    _, call_kwargs = client.update_issue.call_args
    new_body = call_kwargs["body"]
    persisted_json = _extract_state_json(new_body)
    persisted = FeatureState.model_validate_json(persisted_json)
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
    # search_issues returns newest first (higher number first)
    client.search_issues.return_value = [issue_b, issue_a]
    mgr = GitHubStateManager(client)

    # Act
    results = await mgr.list_features()

    # Assert
    assert len(results) == 2
    # Sorted by issue number descending
    assert results[0] == ("feat-20260427-bbb", 2)
    assert results[1] == ("feat-20260427-aaa", 1)


@pytest.mark.asyncio
async def test_list_features_skips_issues_without_feature_label():
    # Arrange
    state = _make_state()
    good_issue = _make_issue(state, number=5)
    # Issue with FEATURE_MARKER but no feature:* label
    bad_issue = {
        "number": 6,
        "body": _build_body(state),
        "labels": [{"name": FEATURE_MARKER}],
    }
    client = _mock_client()
    client.search_issues.return_value = [good_issue, bad_issue]
    mgr = GitHubStateManager(client)

    # Act
    results = await mgr.list_features()

    # Assert — bad_issue silently skipped
    assert len(results) == 1
    assert results[0][0] == state.feature_id


@pytest.mark.asyncio
async def test_list_features_returns_empty_when_no_issues():
    # Arrange
    client = _mock_client()
    client.search_issues.return_value = []
    mgr = GitHubStateManager(client)

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

    with patch(
        "agentharness.github_client.GitHubClient.from_config",
        return_value=AsyncMock(),
    ) as mock_from_config:
        # Act
        mgr = GitHubStateManager.from_config(config)

        # Assert
        mock_from_config.assert_called_once_with(config)
        assert isinstance(mgr, GitHubStateManager)
