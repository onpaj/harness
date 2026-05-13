"""Tests for epic-aware _convert_raw_issue: per-child branches and umbrella PR."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.models import FeatureState, FeatureStatus


def _make_config(max_revisions: int = 3) -> MagicMock:
    config = MagicMock()
    config.storage_backend = "github"
    config.defaults.max_revisions = max_revisions
    config.defaults.dead_letter_threshold = 3
    config.max_analyst_iterations = 2
    config.github.feature_marker = "agentharness-feature"
    return config


def _make_gh_client(
    child_issue_number: int = 55,
    parent_issue_number: int = 10,
    parent_title: str = "My Epic",
    child_title: str = "Child Feature",
    sub_issue_numbers: list[int] | None = None,
) -> MagicMock:
    from agentharness.github_client import GitHubClient

    client = MagicMock(spec=GitHubClient)
    if sub_issue_numbers is None:
        sub_issue_numbers = [child_issue_number]

    child_issue = {
        "number": child_issue_number,
        "title": child_title,
        "body": f"# {child_title}\n\nDo the thing.",
        "labels": [{"name": "agentharness-feature"}],
        "parent_issue": {"number": parent_issue_number, "title": parent_title},
    }
    parent_issue = {"number": parent_issue_number, "title": parent_title}
    sub_issues = [{"number": n, "title": f"Sub {n}"} for n in sub_issue_numbers]

    client.list_issues = AsyncMock(return_value=[child_issue])
    client.get_parent_issue = AsyncMock(return_value=parent_issue)
    client.list_sub_issues = AsyncMock(return_value=sub_issues)
    client.get_default_branch = AsyncMock(return_value="main")
    client.get_ref = AsyncMock(return_value={"object": {"sha": "def-sha"}})
    client.create_ref = AsyncMock()
    client.list_pull_requests = AsyncMock(return_value=[])
    client.create_pull_request = AsyncMock(return_value={"number": 77, "html_url": "https://example.com/pull/77"})
    client.close = AsyncMock()
    return client


class TestConvertRawIssueEpic:
    @pytest.mark.asyncio
    async def test_child_gets_own_branch_off_epic(self):
        """Child issue gets feat-<slug> branch off epic-<slug>, not the shared epic branch."""
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        gh_client = _make_gh_client(child_issue_number=55, parent_issue_number=10)

        store = MagicMock()
        store.upload = AsyncMock()
        store.close = AsyncMock()

        state_captured: list[FeatureState] = []

        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock(side_effect=lambda num, s, **kw: state_captured.append(s))
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.github_state.ensure_epic_branch", new=AsyncMock(return_value="epic-sha")),
            patch("agentharness.github_state.ensure_child_branch", new=AsyncMock()),
            patch("agentharness.github_state.ensure_epic_pr", new=AsyncMock(return_value={"number": 77})),
        ):
            await _convert_raw_issue("feat-child-feature", config)

        assert len(state_captured) == 1
        state = state_captured[0]
        # Child branch is the child's own feature_id, NOT the shared epic branch
        assert state.branch_name == "feat-child-feature"
        assert state.epic_branch == "epic-my-epic"
        assert state.epic_parent == 10
        assert state.epic_position == 1

    @pytest.mark.asyncio
    async def test_ensure_epic_branch_called_with_default_sha(self):
        """ensure_epic_branch is called with the correct epic branch name and default SHA."""
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        gh_client = _make_gh_client()

        store = MagicMock()
        store.upload = AsyncMock()
        store.close = AsyncMock()
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()

        mock_ensure_epic = AsyncMock(return_value="epic-sha-123")

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.github_state.ensure_epic_branch", mock_ensure_epic),
            patch("agentharness.github_state.ensure_child_branch", new=AsyncMock()),
            patch("agentharness.github_state.ensure_epic_pr", new=AsyncMock(return_value={"number": 77})),
        ):
            await _convert_raw_issue("feat-child-feature", config)

        mock_ensure_epic.assert_called_once_with(gh_client, "epic-my-epic", "def-sha")

    @pytest.mark.asyncio
    async def test_no_prev_sibling_gate_for_second_child(self):
        """Second child can start without waiting for first child to be done."""
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        # Two sub-issues; this child is issue #56 (second)
        gh_client = _make_gh_client(
            child_issue_number=56,
            parent_issue_number=10,
            child_title="Sub 56",
            sub_issue_numbers=[55, 56],
        )
        store = MagicMock()
        store.upload = AsyncMock()
        store.close = AsyncMock()
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()
        state_mgr.get = AsyncMock(side_effect=KeyError("feat-sub-55"))

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.github_state.ensure_epic_branch", new=AsyncMock(return_value="sha")),
            patch("agentharness.github_state.ensure_child_branch", new=AsyncMock()),
            patch("agentharness.github_state.ensure_epic_pr", new=AsyncMock(return_value={"number": 77})),
        ):
            # Should NOT raise even though sibling is not done
            await _convert_raw_issue("feat-sub-56", config)

        state_mgr.get.assert_not_called()  # prev-sibling gate removed
