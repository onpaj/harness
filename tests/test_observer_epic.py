"""Tests for epic awareness in observer._bootstrap_github_issue."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.models import FeatureState, FeatureStatus


def _make_config() -> MagicMock:
    config = MagicMock()
    config.storage_backend = "github"
    config.defaults.max_revisions = 3
    config.defaults.dead_letter_threshold = 3
    config.max_analyst_iterations = 2
    config.github.feature_marker = "agentharness-feature"
    return config


def _make_client(
    child_number: int = 55,
    child_title: str = "Child Feature",
    parent_number: int = 10,
    parent_title: str = "Parent Epic",
) -> MagicMock:
    from agentharness.github_client import GitHubClient

    client = MagicMock(spec=GitHubClient)
    parent_issue = {"number": parent_number, "title": parent_title}
    client.get_parent_issue = AsyncMock(return_value=parent_issue)
    client.get_default_branch = AsyncMock(return_value="main")
    client.get_ref = AsyncMock(return_value={"object": {"sha": "main-sha"}})
    client.create_ref = AsyncMock()
    client.put_content = AsyncMock()
    client.create_issue = AsyncMock(return_value={"number": 99})
    client.update_issue = AsyncMock()
    client.ensure_labels = AsyncMock()
    client.add_labels = AsyncMock()
    client.get_issue = AsyncMock(return_value={"number": 99, "body": ""})
    return client


class TestBootstrapGithubIssueEpic:
    @pytest.mark.asyncio
    async def test_epic_child_creates_branch_off_epic_branch(self):
        """When issue has a parent, branch is created off epic branch, not default."""
        from agentharness.observer import _bootstrap_github_issue

        config = _make_config()
        client = _make_client(child_number=55, parent_number=10, parent_title="My Epic")
        issue = {"number": 55, "title": "Child Feature", "body": "Do the work."}

        mock_ensure_epic = AsyncMock(return_value="epic-sha")
        mock_ensure_child = AsyncMock()

        with (
            patch("agentharness.observer.ensure_epic_branch", mock_ensure_epic),
            patch("agentharness.observer.ensure_child_branch", mock_ensure_child),
            patch("agentharness.github_state.GitHubStateManager.create", AsyncMock()),
        ):
            result = await _bootstrap_github_issue(client, issue, config)

        assert result == "feat-child-feature"
        mock_ensure_epic.assert_called_once_with(client, "epic-my-epic", "main-sha")
        mock_ensure_child.assert_called_once()
        child_branch_arg = mock_ensure_child.call_args.args[1]
        assert child_branch_arg == "feat-child-feature"  # NOT "epic-my-epic"

    @pytest.mark.asyncio
    async def test_non_epic_issue_creates_branch_off_default(self):
        """Non-epic issue: branch created off default branch as before."""
        from agentharness.observer import _bootstrap_github_issue

        config = _make_config()
        client = _make_client()
        client.get_parent_issue = AsyncMock(return_value=None)  # no parent
        issue = {"number": 55, "title": "Standalone Feature", "body": "Do the thing."}

        with (
            patch("agentharness.observer.ensure_epic_branch") as mock_epic,
            patch("agentharness.observer.ensure_child_branch") as mock_child,
            patch("agentharness.github_state.GitHubStateManager.create", AsyncMock()),
        ):
            await _bootstrap_github_issue(client, issue, config)

        mock_epic.assert_not_called()
        mock_child.assert_not_called()
        client.create_ref.assert_called_once()

    @pytest.mark.asyncio
    async def test_epic_fields_set_on_feature_state(self):
        """FeatureState created for epic child has epic_parent and epic_branch populated."""
        from agentharness.observer import _bootstrap_github_issue
        from agentharness.github_state import GitHubStateManager

        config = _make_config()
        client = _make_client(child_number=55, parent_number=10, parent_title="My Epic")
        issue = {"number": 55, "title": "Child Feature", "body": "Do the work."}

        created_states: list[FeatureState] = []

        async def capture_create(self_mgr, state, brief=""):
            created_states.append(state)

        with (
            patch("agentharness.observer.ensure_epic_branch", AsyncMock(return_value="epic-sha")),
            patch("agentharness.observer.ensure_child_branch", AsyncMock()),
            patch.object(GitHubStateManager, "create", capture_create),
        ):
            await _bootstrap_github_issue(client, issue, config)

        assert len(created_states) == 1
        state = created_states[0]
        assert state.epic_parent == 10
        assert state.epic_branch == "epic-my-epic"
        assert state.branch_name == "feat-child-feature"
