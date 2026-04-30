"""Tests for CLI epic gating via _implement_with_epic_check function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.cli import _implement_with_epic_check


@pytest.mark.asyncio
async def test_implement_non_github_backend_skips_check() -> None:
    """Non-GitHub backend: skips all checks and calls enqueue_planner."""
    config = MagicMock()
    config.storage_backend = "azure"

    mock_enqueue_planner = AsyncMock()
    mock_console_print = MagicMock()

    with patch("agentharness.cli.enqueue_planner", mock_enqueue_planner):
        with patch("agentharness.cli.console.print", mock_console_print):
            await _implement_with_epic_check("feat-test-123", config)

    # Should call enqueue_planner without touching state_mgr or gh_client
    mock_enqueue_planner.assert_called_once_with("feat-test-123", config)


@pytest.mark.asyncio
async def test_implement_no_existing_state_proceeds() -> None:
    """KeyError from state_mgr.get: proceeds to enqueue_planner normally."""
    config = MagicMock()
    config.storage_backend = "github"

    # Mock state manager that raises KeyError
    mock_state_mgr = MagicMock()
    mock_state_mgr.get = AsyncMock(side_effect=KeyError("not found"))

    # Mock GitHub client
    mock_gh_client = MagicMock()
    mock_gh_client.close = AsyncMock()

    mock_enqueue_planner = AsyncMock()
    mock_console_print = MagicMock()

    with patch("agentharness.cli.create_state_manager", return_value=mock_state_mgr):
        with patch("agentharness.cli.GitHubClient.from_config", return_value=mock_gh_client):
            with patch("agentharness.cli.enqueue_planner", mock_enqueue_planner):
                with patch("agentharness.cli.console.print", mock_console_print):
                    await _implement_with_epic_check("feat-test-123", config)

    # Should try to get state, fail with KeyError, then proceed to enqueue
    mock_state_mgr.get.assert_called_once_with("feat-test-123")
    mock_enqueue_planner.assert_called_once_with("feat-test-123", config)
    mock_gh_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_implement_non_epic_feature_proceeds() -> None:
    """State has epic_parent=None: proceeds normally without checking parent."""
    config = MagicMock()
    config.storage_backend = "github"

    # Create mock state with no epic parent
    mock_state = MagicMock()
    mock_state.epic_parent = None

    mock_state_mgr = MagicMock()
    mock_state_mgr.get = AsyncMock(return_value=mock_state)

    mock_gh_client = MagicMock()
    mock_gh_client.close = AsyncMock()
    mock_gh_client.get_issue = AsyncMock()

    mock_enqueue_planner = AsyncMock()
    mock_console_print = MagicMock()

    with patch("agentharness.cli.create_state_manager", return_value=mock_state_mgr):
        with patch("agentharness.cli.GitHubClient.from_config", return_value=mock_gh_client):
            with patch("agentharness.cli.enqueue_planner", mock_enqueue_planner):
                with patch("agentharness.cli.console.print", mock_console_print):
                    await _implement_with_epic_check("feat-test-123", config)

    # Should load state but NOT call get_issue (no epic parent)
    mock_state_mgr.get.assert_called_once_with("feat-test-123")
    mock_gh_client.get_issue.assert_not_called()
    mock_enqueue_planner.assert_called_once_with("feat-test-123", config)
    mock_gh_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_implement_epic_paused_exits() -> None:
    """State has epic_parent=5, parent has epic:paused label: exits with error."""
    config = MagicMock()
    config.storage_backend = "github"

    # Create mock state with epic parent
    mock_state = MagicMock()
    mock_state.epic_parent = 5

    mock_state_mgr = MagicMock()
    mock_state_mgr.get = AsyncMock(return_value=mock_state)

    # Mock parent issue with epic:paused label
    parent_issue = {
        "number": 5,
        "labels": [
            {"name": "epic:paused"},
        ],
    }

    mock_gh_client = MagicMock()
    mock_gh_client.get_issue = AsyncMock(return_value=parent_issue)
    mock_gh_client.close = AsyncMock()

    mock_enqueue_planner = AsyncMock()
    mock_console_print = MagicMock()

    with patch("agentharness.cli.create_state_manager", return_value=mock_state_mgr):
        with patch("agentharness.cli.GitHubClient.from_config", return_value=mock_gh_client):
            with patch("agentharness.cli.enqueue_planner", mock_enqueue_planner):
                with patch("agentharness.cli.console.print", mock_console_print):
                    with pytest.raises(SystemExit) as exc_info:
                        await _implement_with_epic_check("feat-test-123", config)

    # Should exit with code 1
    assert exc_info.value.code == 1

    # Should have printed error messages
    calls = [str(call) for call in mock_console_print.call_args_list]
    output = " ".join(calls)
    assert "Epic is paused" in output

    # Should NOT have called enqueue_planner
    mock_enqueue_planner.assert_not_called()

    # Should have closed client
    mock_gh_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_implement_epic_not_paused_proceeds() -> None:
    """State has epic_parent=5, parent has no epic:paused label: proceeds normally."""
    config = MagicMock()
    config.storage_backend = "github"

    # Create mock state with epic parent
    mock_state = MagicMock()
    mock_state.epic_parent = 5

    mock_state_mgr = MagicMock()
    mock_state_mgr.get = AsyncMock(return_value=mock_state)

    # Mock parent issue WITHOUT epic:paused label
    parent_issue = {
        "number": 5,
        "labels": [
            {"name": "epic"},
        ],
    }

    mock_gh_client = MagicMock()
    mock_gh_client.get_issue = AsyncMock(return_value=parent_issue)
    mock_gh_client.close = AsyncMock()

    mock_enqueue_planner = AsyncMock()
    mock_console_print = MagicMock()

    with patch("agentharness.cli.create_state_manager", return_value=mock_state_mgr):
        with patch("agentharness.cli.GitHubClient.from_config", return_value=mock_gh_client):
            with patch("agentharness.cli.enqueue_planner", mock_enqueue_planner):
                with patch("agentharness.cli.console.print", mock_console_print):
                    await _implement_with_epic_check("feat-test-123", config)

    # Should proceed normally
    mock_gh_client.get_issue.assert_called_once_with(5)
    mock_enqueue_planner.assert_called_once_with("feat-test-123", config)
    mock_gh_client.close.assert_called_once()
