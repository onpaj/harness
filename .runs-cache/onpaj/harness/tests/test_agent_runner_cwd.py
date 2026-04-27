"""Tests verifying cwd injection from worktree_path in run_agent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.agent_runner import run_agent
from agentharness.models import AgentDefinition


def _make_agent_def(agent_id: str = "developer", **overrides) -> AgentDefinition:
    defaults = dict(
        id=agent_id,
        model="claude-sonnet-4-6",
        phase="developing",
        system_prompt="You are an agent.",
        visibility_timeout=600,
    )
    return AgentDefinition(**{**defaults, **overrides})


def _mock_subprocess(stdout_lines: list[bytes] = None, returncode: int = 0):
    """Return a mock asyncio subprocess with controlled stdout/stderr."""
    if stdout_lines is None:
        stdout_lines = [b"output line\n"]

    async def fake_stdout():
        for line in stdout_lines:
            yield line

    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = fake_stdout()
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    return proc


@pytest.mark.asyncio
async def test_worktree_path_used_as_cwd(tmp_path: Path) -> None:
    """When worktree_path is set, subprocess cwd equals that path."""
    worktree = str(tmp_path / "worktree")
    agent_def = _make_agent_def("developer")
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _mock_subprocess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await run_agent(agent_def, "do work", worktree_path=worktree)

    assert captured["cwd"] == worktree


@pytest.mark.asyncio
async def test_no_worktree_path_uses_work_dir(tmp_path: Path) -> None:
    """When worktree_path is None, subprocess cwd equals work_dir."""
    agent_def = _make_agent_def("planner")
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _mock_subprocess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await run_agent(agent_def, "plan it", work_dir=tmp_path, worktree_path=None)

    assert captured["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_worktree_path_overrides_work_dir(tmp_path: Path) -> None:
    """worktree_path takes precedence over work_dir for subprocess cwd."""
    worktree = str(tmp_path / "isolated")
    work_dir = tmp_path / "artifacts"
    work_dir.mkdir()
    agent_def = _make_agent_def("reviewer")
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _mock_subprocess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await run_agent(agent_def, "review it", work_dir=work_dir, worktree_path=worktree)

    assert captured["cwd"] == worktree


@pytest.mark.asyncio
async def test_no_worktree_no_work_dir_uses_temp_dir() -> None:
    """When both are None, subprocess cwd is an auto-created temp dir (not None)."""
    agent_def = _make_agent_def("analyst")
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _mock_subprocess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await run_agent(agent_def, "analyse", work_dir=None, worktree_path=None)

    assert captured["cwd"] is not None
    assert "agent-analyst-" in captured["cwd"]


@pytest.mark.asyncio
async def test_cwd_injection_for_planner_agent(tmp_path: Path) -> None:
    """Confirms worktree_path injection applies to planner agent type."""
    worktree = str(tmp_path / "planner-worktree")
    agent_def = _make_agent_def("planner", phase="planning")
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _mock_subprocess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await run_agent(agent_def, "plan tasks", worktree_path=worktree)

    assert captured["cwd"] == worktree
