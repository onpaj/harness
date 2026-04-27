"""Tests for worker.py git worktree integration (creation hook + startup probes)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentharness.config import Config, ConfigError, DefaultsConfig, QueueConfig, StorageConfig
from agentharness.models import AgentDefinition, FeatureState, FeatureStatus, TaskMessage
from agentharness.worker import Worker, check_worktree_startup_probes
from agentharness.worktree_manager import WorktreeCreationError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_agent_def(**overrides) -> AgentDefinition:
    defaults = dict(
        id="developer",
        model="claude-sonnet-4-6",
        phase="developing",
        system_prompt="You are a developer agent.",
        visibility_timeout=1800,
    )
    return AgentDefinition(**{**defaults, **overrides})


def _make_task(feature_id: str = "feat-abc123", task_id: str = "feat-abc123-dev-auth") -> TaskMessage:
    return TaskMessage(
        feature_id=feature_id,
        task_id=task_id,
        input_artifacts=[],
        output_artifact=f"artifacts/{feature_id}/impl/{task_id}.r1.md",
        agent_role="developer",
        context="Implement auth",
    )


def _make_config(use_worktrees: bool = False) -> Config:
    queue_cfg = QueueConfig(agent=".agents/developer.md", context_files=None)
    return Config(
        storage=StorageConfig(connection_string_env="FAKE_ENV"),
        queues={"developer-queue": queue_cfg},
        defaults=DefaultsConfig(),
        config_dir=Path("/project/.pipeline"),
        use_worktrees=use_worktrees,
        worktree_base_dir=".worktrees",
        worktree_base_branch=None,
    )


def _make_feature_state(feature_id: str = "feat-abc123", worktree_path: str | None = None) -> FeatureState:
    return FeatureState(
        feature_id=feature_id,
        status=FeatureStatus.developing,
        worktree_path=worktree_path,
    )


def _make_worker(config: Config, queue_name: str = "developer-queue") -> Worker:
    return Worker(
        queue_name=queue_name,
        queue=AsyncMock(),
        artifact_store=AsyncMock(),
        state_manager=AsyncMock(),
        all_queues={queue_name: AsyncMock()},
        config=config,
    )


# ── Startup probe tests ───────────────────────────────────────────────────────


class TestCheckWorktreeStartupProbes:
    """check_worktree_startup_probes() raises ConfigError in invalid environments."""

    def test_raises_on_windows(self):
        with patch("agentharness.worker.os") as mock_os:
            mock_os.name = "nt"
            with pytest.raises(ConfigError, match="Windows"):
                check_worktree_startup_probes()

    def test_raises_when_git_version_below_2_5(self):
        version_output = "git version 2.4.11"
        with (
            patch("agentharness.worker.os") as mock_os,
            patch("agentharness.worker.subprocess") as mock_subprocess,
        ):
            mock_os.name = "posix"
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=0, stdout=version_output),
                MagicMock(returncode=0, stdout=".git"),
            ]
            with pytest.raises(ConfigError, match="2.5"):
                check_worktree_startup_probes()

    def test_raises_when_not_in_git_repo(self):
        version_output = "git version 2.40.1"
        with (
            patch("agentharness.worker.os") as mock_os,
            patch("agentharness.worker.subprocess") as mock_subprocess,
        ):
            mock_os.name = "posix"
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=0, stdout=version_output),
                MagicMock(returncode=128, stdout="", stderr="not a git repository"),
            ]
            with pytest.raises(ConfigError, match="git repo"):
                check_worktree_startup_probes()

    def test_passes_on_valid_environment(self):
        version_output = "git version 2.40.1"
        with (
            patch("agentharness.worker.os") as mock_os,
            patch("agentharness.worker.subprocess") as mock_subprocess,
        ):
            mock_os.name = "posix"
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=0, stdout=version_output),
                MagicMock(returncode=0, stdout=".git"),
            ]
            # Should not raise
            check_worktree_startup_probes()

    def test_raises_on_git_2_5_exactly_passes(self):
        version_output = "git version 2.5.0"
        with (
            patch("agentharness.worker.os") as mock_os,
            patch("agentharness.worker.subprocess") as mock_subprocess,
        ):
            mock_os.name = "posix"
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=0, stdout=version_output),
                MagicMock(returncode=0, stdout=".git"),
            ]
            # 2.5.0 is exactly the minimum — should pass
            check_worktree_startup_probes()


# ── Worktree creation on first task ──────────────────────────────────────────


class TestWorktreeCreationOnFirstTask:
    """Worktree is created before agent runs on the first task when use_worktrees=True."""

    def _setup_worker(self, *, use_worktrees: bool, initial_worktree_path: str | None = None):
        config = _make_config(use_worktrees=use_worktrees)
        worker = _make_worker(config)

        feature_state = _make_feature_state(worktree_path=initial_worktree_path)
        updated_state = _make_feature_state(worktree_path="/repo/.worktrees/feat-abc123")

        worker._state.get = AsyncMock(side_effect=[feature_state, updated_state])
        worker._state.update = AsyncMock(return_value=feature_state)
        worker._state.set_worktree_path = AsyncMock()
        worker._store.download = AsyncMock(return_value="artifact content")
        worker._store.upload = AsyncMock()

        return worker

    @pytest.mark.asyncio
    async def test_worktree_created_before_agent_runs(self):
        """set_worktree_path is called before run_agent when use_worktrees=True."""
        worker = self._setup_worker(use_worktrees=True)
        task = _make_task()
        agent_def = _make_agent_def()
        call_order = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_order.append("create_worktree")
            return "/repo/.worktrees/feat-abc123"

        async def mock_set_worktree_path(feature_id, path):
            call_order.append("set_worktree_path")

        async def mock_run_agent(*args, **kwargs):
            call_order.append("run_agent")
            return "## Status: DONE"

        worker._state.set_worktree_path = mock_set_worktree_path

        with (
            patch("agentharness.worker.asyncio.to_thread", side_effect=mock_to_thread),
            patch("agentharness.worker.run_agent", side_effect=mock_run_agent),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await worker._process_task(task, agent_def)

        assert call_order.index("create_worktree") < call_order.index("set_worktree_path")
        assert call_order.index("set_worktree_path") < call_order.index("run_agent")

    @pytest.mark.asyncio
    async def test_worktree_path_persisted_in_state(self):
        """set_worktree_path is called with the returned path."""
        worker = self._setup_worker(use_worktrees=True)
        task = _make_task()
        agent_def = _make_agent_def()
        expected_path = "/repo/.worktrees/feat-abc123"

        with (
            patch("agentharness.worker.asyncio.to_thread", new_callable=AsyncMock, return_value=expected_path),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="## Status: DONE"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await worker._process_task(task, agent_def)

        worker._state.set_worktree_path.assert_awaited_once_with("feat-abc123", expected_path)

    @pytest.mark.asyncio
    async def test_no_worktree_when_disabled(self):
        """create_worktree is never called when use_worktrees=False."""
        worker = self._setup_worker(use_worktrees=False, initial_worktree_path=None)
        # Only one state.get call when worktrees disabled
        feature_state = _make_feature_state(worktree_path=None)
        worker._state.get = AsyncMock(return_value=feature_state)
        task = _make_task()
        agent_def = _make_agent_def()

        with (
            patch("agentharness.worker.asyncio.to_thread") as mock_thread,
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="## Status: DONE"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await worker._process_task(task, agent_def)

        mock_thread.assert_not_called()
        worker._state.set_worktree_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_worktree_created_when_already_set(self):
        """create_worktree is not called again when worktree_path is already set."""
        existing_path = "/repo/.worktrees/feat-abc123"
        worker = self._setup_worker(use_worktrees=True, initial_worktree_path=existing_path)
        # When worktree already set, only one state.get call
        feature_state = _make_feature_state(worktree_path=existing_path)
        worker._state.get = AsyncMock(return_value=feature_state)
        task = _make_task()
        agent_def = _make_agent_def()

        with (
            patch("agentharness.worker.asyncio.to_thread") as mock_thread,
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="## Status: DONE"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await worker._process_task(task, agent_def)

        mock_thread.assert_not_called()


# ── Worktree creation failure ─────────────────────────────────────────────────


class TestWorktreeCreationFailure:
    """WorktreeCreationError causes feature to fail; agent is never run."""

    @pytest.mark.asyncio
    async def test_feature_fails_on_creation_error(self):
        config = _make_config(use_worktrees=True)
        worker = _make_worker(config)
        feature_state = _make_feature_state()

        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)
        worker._state.set_worktree_path = AsyncMock()

        task = _make_task()
        agent_def = _make_agent_def()

        exc = WorktreeCreationError(
            "git worktree add failed",
            command=["git", "worktree", "add", "/path"],
            stderr="fatal: branch already exists",
            returncode=128,
        )

        with (
            patch("agentharness.worker.asyncio.to_thread", new_callable=AsyncMock, side_effect=exc),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock) as mock_agent,
        ):
            await worker._process_task(task, agent_def)

        mock_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_updated_to_failed_on_creation_error(self):
        config = _make_config(use_worktrees=True)
        worker = _make_worker(config)
        feature_state = _make_feature_state()

        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)

        task = _make_task()
        agent_def = _make_agent_def()

        exc = WorktreeCreationError(
            "git worktree add failed",
            command=["git", "worktree", "add", "/path"],
            stderr="fatal: branch already exists",
            returncode=128,
        )

        with (
            patch("agentharness.worker.asyncio.to_thread", new_callable=AsyncMock, side_effect=exc),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock),
        ):
            await worker._process_task(task, agent_def)

        # state.update should have been called with a function that transitions to failed
        worker._state.update.assert_awaited()
        update_fn = worker._state.update.call_args[0][1]
        result_state = update_fn(feature_state)
        assert result_state.status == FeatureStatus.failed

    @pytest.mark.asyncio
    async def test_structured_error_details_in_state(self):
        config = _make_config(use_worktrees=True)
        worker = _make_worker(config)
        feature_state = _make_feature_state()

        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)

        task = _make_task()
        agent_def = _make_agent_def()

        exc = WorktreeCreationError(
            "git worktree add failed",
            command=["git", "worktree", "add", "/path"],
            stderr="fatal: branch already exists",
            returncode=128,
        )

        with (
            patch("agentharness.worker.asyncio.to_thread", new_callable=AsyncMock, side_effect=exc),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock),
        ):
            await worker._process_task(task, agent_def)

        update_fn = worker._state.update.call_args[0][1]
        result_state = update_fn(feature_state)
        event = result_state.history[-1]
        assert event.event == "feature_failed"
        assert "worktree_creation" in (event.details or "")


# ── Concurrency: parallel features ───────────────────────────────────────────


class TestConcurrentWorktreeCreation:
    """Concurrent _process_task calls for different features complete independently."""

    @pytest.mark.asyncio
    async def test_two_concurrent_features_both_complete(self):
        """Two concurrent process_task coroutines finish even with simulated async worktree creation."""
        config = _make_config(use_worktrees=True)
        completed = []

        async def slow_to_thread(fn, *args, **kwargs):
            feature_id = args[0]
            await asyncio.sleep(0.01)
            return f"/repo/.worktrees/{feature_id}"

        async def process_feature(feature_id: str):
            worker = _make_worker(config)
            state = _make_feature_state(feature_id=feature_id)
            updated_state = _make_feature_state(feature_id=feature_id, worktree_path=f"/repo/.worktrees/{feature_id}")
            worker._state.get = AsyncMock(side_effect=[state, updated_state])
            worker._state.update = AsyncMock(return_value=state)
            worker._state.set_worktree_path = AsyncMock()
            worker._store.upload = AsyncMock()
            worker._store.download = AsyncMock(return_value="content")
            task = _make_task(feature_id=feature_id, task_id=f"{feature_id}-dev-task")
            agent_def = _make_agent_def()
            await worker._process_task(task, agent_def)
            completed.append(feature_id)

        # Patches applied at outer scope so they stay active across concurrent coroutines.
        # Per-coroutine patching causes a patch-stack race when one coroutine's __exit__
        # restores the original before the other coroutine has finished using the mock.
        with (
            patch("agentharness.worker.asyncio.to_thread", side_effect=slow_to_thread),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="## Status: DONE"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await asyncio.gather(
                process_feature("feat-aaa111"),
                process_feature("feat-bbb222"),
            )

        assert "feat-aaa111" in completed
        assert "feat-bbb222" in completed


# ── Invalid feature_id at intake ──────────────────────────────────────────────


class TestInvalidFeatureIdAtIntake:
    """Tasks with invalid feature_id are rejected before any agent work."""

    @pytest.mark.asyncio
    async def test_invalid_feature_id_fails_feature(self):
        config = _make_config(use_worktrees=True)
        worker = _make_worker(config)

        feature_state = _make_feature_state()
        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)

        # Craft a task with an invalid feature_id (contains path traversal)
        task = TaskMessage(
            feature_id="../../../etc/passwd",
            task_id="task-1",
            input_artifacts=[],
            output_artifact="artifacts/out.md",
            agent_role="developer",
        )
        agent_def = _make_agent_def()

        with patch("agentharness.worker.run_agent", new_callable=AsyncMock) as mock_agent:
            await worker._process_task(task, agent_def)

        mock_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_feature_id_marks_failed(self):
        config = _make_config(use_worktrees=True)
        worker = _make_worker(config)

        feature_state = _make_feature_state()
        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)

        task = TaskMessage(
            feature_id="../../../etc/passwd",
            task_id="task-1",
            input_artifacts=[],
            output_artifact="artifacts/out.md",
            agent_role="developer",
        )
        agent_def = _make_agent_def()

        with patch("agentharness.worker.run_agent", new_callable=AsyncMock):
            await worker._process_task(task, agent_def)

        # The phase guard check: status.value != agent_def.phase means it returns early.
        # With invalid ID, it should fail (update called) or return early from phase guard.
        # Either way, agent must not run.
        # Phase guard returns early since feature_state.status.value == "developing" == phase,
        # so we check state.update was called with a failed transition.
        worker._state.update.assert_awaited()
        update_fn = worker._state.update.call_args[0][1]
        result_state = update_fn(feature_state)
        assert result_state.status == FeatureStatus.failed
