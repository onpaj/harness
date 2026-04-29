"""Tests that upload_brief propagates max_analyst_iterations from config into PipelineConfig."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.brainstorm import upload_brief
from agentharness.models import FeatureStatus


@pytest.mark.asyncio
async def test_upload_brief_propagates_max_analyst_iterations() -> None:
    """upload_brief propagates max_analyst_iterations from config into PipelineConfig."""
    config = MagicMock()
    config.storage_backend = "github"
    config.defaults.max_revisions = 4
    config.max_analyst_iterations = 7

    captured: dict = {}

    async def fake_create(state, **_):
        captured["state"] = state

    fake_state_mgr = MagicMock()
    fake_state_mgr.create = AsyncMock(side_effect=fake_create)

    fake_store = MagicMock()
    fake_store.upload = AsyncMock()
    fake_store.close = AsyncMock()

    with (
        patch("agentharness.brainstorm.create_artifact_store", return_value=fake_store),
        patch("agentharness.brainstorm.create_state_manager", return_value=fake_state_mgr),
    ):
        await upload_brief("feat-test", "# Brief\n\ncontent", config)

    state = captured["state"]
    assert state.config.max_revisions == 4
    assert state.config.max_analyst_iterations == 7
    assert state.config.current_analyst_iteration == 0
    assert state.status == FeatureStatus.brainstormed
