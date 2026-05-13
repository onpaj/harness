"""Tests for the agentharness convert CLI subcommand."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from agentharness.cli import main


def test_convert_exits_zero_when_successful():
    """agentharness convert <issue_number> succeeds and exits 0."""
    runner = CliRunner()

    mock_config = MagicMock()
    mock_issue = {"number": 42, "title": "My Feature"}

    async def fake_convert(feature_id, config):
        pass

    with (
        patch("agentharness.cli.load_config", return_value=mock_config),
        patch("agentharness.cli._convert_raw_issue", side_effect=fake_convert),
        patch("agentharness.cli.GitHubClient") as mock_gh_cls,
    ):
        mock_gh_instance = MagicMock()
        mock_gh_instance.get_issue = AsyncMock(return_value=mock_issue)
        mock_gh_instance.close = AsyncMock()
        mock_gh_cls.from_config.return_value = mock_gh_instance

        result = runner.invoke(main, ["convert", "42"])

    assert result.exit_code == 0, result.output
    assert "feat-my-feature" in result.output


def test_convert_exits_nonzero_when_issue_not_found():
    """agentharness convert <issue_number> exits non-zero when GitHub returns 404."""
    runner = CliRunner()

    mock_config = MagicMock()

    with (
        patch("agentharness.cli.load_config", return_value=mock_config),
        patch("agentharness.cli.GitHubClient") as mock_gh_cls,
    ):
        from agentharness.github_client import GitHubApiError
        mock_gh_instance = MagicMock()
        mock_gh_instance.get_issue = AsyncMock(side_effect=GitHubApiError(404, "Not Found"))
        mock_gh_instance.close = AsyncMock()
        mock_gh_cls.from_config.return_value = mock_gh_instance

        result = runner.invoke(main, ["convert", "999"])

    assert result.exit_code != 0
