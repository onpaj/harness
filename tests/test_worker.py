"""Unit tests for Worker dispatch-layer context file caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.config import Config, QueueConfig, StorageConfig, DefaultsConfig
from agentharness.context_files import ContextFileResult, ResolvedContextFile
from agentharness.models import AgentDefinition, FeatureState, FeatureStatus, TaskMessage
from agentharness.worker import Worker


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_agent_def(**overrides) -> AgentDefinition:
    defaults = dict(
        id="developer",
        model="claude-sonnet-4-6",
        phase="developing",
        system_prompt="You are a developer agent.",
        visibility_timeout=1800,
    )
    return AgentDefinition(**{**defaults, **overrides})


def _make_task(task_id: str = "feat-1-dev-auth") -> TaskMessage:
    return TaskMessage(
        feature_id="feat-1",
        task_id=task_id,
        input_artifacts=[],
        output_artifact=f"artifacts/feat-1/impl/{task_id}.r1.md",
        agent_role="developer",
        context="Implement auth",
    )


def _make_config(context_files: list[str] | None = None) -> Config:
    queue_cfg = QueueConfig(agent=".agents/developer.md", context_files=context_files)
    cfg = Config(
        storage=StorageConfig(connection_string_env="FAKE_ENV"),
        queues={"developer-queue": queue_cfg},
        defaults=DefaultsConfig(),
        config_dir=Path("/project/.pipeline"),
    )
    return cfg


def _make_context_result(agent_name: str = "developer") -> ContextFileResult:
    file = ResolvedContextFile(
        declared_path="standards.md",
        resolved_path=Path("/project/.pipeline/standards.md"),
        display_path="standards.md",
        content="# Coding Standards\n\nUse type hints.",
        size_bytes=34,
    )
    return ContextFileResult(
        agent_name=agent_name,
        files=(file,),
        warnings=(),
        total_bytes=34,
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


# ── _resolve_context_files_cached ───────────────────────────────────────────

class TestResolveContextFilesCached:
    def test_returns_none_when_no_context_files(self):
        worker = _make_worker(_make_config(context_files=None))
        result = worker._resolve_context_files_cached("feat-1-dev-auth")
        assert result is None

    def test_returns_none_when_context_files_empty_list(self):
        cfg = _make_config(context_files=None)
        worker = _make_worker(cfg)
        result = worker._resolve_context_files_cached("feat-1-dev-auth")
        assert result is None

    def test_calls_resolve_on_first_dispatch(self):
        cfg = _make_config(context_files=["standards.md"])
        worker = _make_worker(cfg)
        expected = _make_context_result()

        with patch(
            "agentharness.worker.resolve_context_files", return_value=expected
        ) as mock_resolve:
            result = worker._resolve_context_files_cached("feat-1-dev-auth")

        mock_resolve.assert_called_once_with(
            ["standards.md"], "developer", Path("/project/.pipeline")
        )
        assert result is expected

    def test_caches_result_on_retry(self):
        cfg = _make_config(context_files=["standards.md"])
        worker = _make_worker(cfg)
        expected = _make_context_result()

        with patch(
            "agentharness.worker.resolve_context_files", return_value=expected
        ) as mock_resolve:
            first = worker._resolve_context_files_cached("feat-1-dev-auth")
            second = worker._resolve_context_files_cached("feat-1-dev-auth")

        assert mock_resolve.call_count == 1
        assert first is expected
        assert second is expected

    def test_reads_fresh_for_new_task(self):
        cfg = _make_config(context_files=["standards.md"])
        worker = _make_worker(cfg)
        result_a = _make_context_result()
        result_b = _make_context_result()

        with patch(
            "agentharness.worker.resolve_context_files",
            side_effect=[result_a, result_b],
        ) as mock_resolve:
            r1 = worker._resolve_context_files_cached("feat-1-dev-task-a")
            r2 = worker._resolve_context_files_cached("feat-1-dev-task-b")

        assert mock_resolve.call_count == 2
        assert r1 is result_a
        assert r2 is result_b

    def test_uses_agent_stem_as_name(self):
        cfg = _make_config(context_files=["docs/tokens"])
        cfg.queues["developer-queue"] = QueueConfig(
            agent=".agents/designer.md", context_files=["docs/tokens"]
        )
        worker = _make_worker(cfg)

        with patch(
            "agentharness.worker.resolve_context_files",
            return_value=_make_context_result("designer"),
        ) as mock_resolve:
            worker._resolve_context_files_cached("feat-1-dev-ui")

        _, agent_name_arg, _ = mock_resolve.call_args[0]
        assert agent_name_arg == "designer"

    def test_emits_warnings_from_result(self, caplog):
        import logging
        cfg = _make_config(context_files=["missing.md"])
        worker = _make_worker(cfg)
        result_with_warnings = ContextFileResult(
            agent_name="developer",
            files=(),
            warnings=("Skipped unreadable file: missing.md",),
            total_bytes=0,
        )

        with patch(
            "agentharness.worker.resolve_context_files",
            return_value=result_with_warnings,
        ):
            with caplog.at_level(logging.WARNING, logger="agentharness.worker"):
                worker._resolve_context_files_cached("feat-1-dev-auth")

        assert any("missing.md" in r.message for r in caplog.records)


# ── Cache lifecycle via _process_task ────────────────────────────────────────

class TestProcessTaskContextCaching:
    """Integration tests verifying cache is populated then cleared on success."""

    def _setup_worker_mocks(self, config: Config):
        worker = _make_worker(config)

        feature_state = FeatureState(feature_id="feat-1", status=FeatureStatus.developing)
        agent_def = _make_agent_def()

        worker._state.get = AsyncMock(return_value=feature_state)
        worker._state.update = AsyncMock(return_value=feature_state)
        worker._store.download = AsyncMock(return_value="artifact content")
        worker._store.upload = AsyncMock()

        return worker, agent_def

    @pytest.mark.asyncio
    async def test_context_result_passed_to_build_prompt(self):
        cfg = _make_config(context_files=["standards.md"])
        worker, agent_def = self._setup_worker_mocks(cfg)
        task = _make_task()
        context_result = _make_context_result()

        with (
            patch("agentharness.worker.resolve_context_files", return_value=context_result),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="output"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="assembled prompt") as mock_build,
        ):
            await worker._process_task(task, agent_def)

        _, _, _, passed_result = mock_build.call_args[0]
        assert passed_result is context_result

    @pytest.mark.asyncio
    async def test_no_context_result_when_no_context_files(self):
        cfg = _make_config(context_files=None)
        worker, agent_def = self._setup_worker_mocks(cfg)
        task = _make_task()

        with (
            patch("agentharness.worker.resolve_context_files") as mock_resolve,
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="output"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt") as mock_build,
        ):
            await worker._process_task(task, agent_def)

        mock_resolve.assert_not_called()
        _, _, _, passed_result = mock_build.call_args[0]
        assert passed_result is None

    @pytest.mark.asyncio
    async def test_cache_cleared_after_successful_task(self):
        cfg = _make_config(context_files=["standards.md"])
        worker, agent_def = self._setup_worker_mocks(cfg)
        task = _make_task()
        context_result = _make_context_result()

        with (
            patch("agentharness.worker.resolve_context_files", return_value=context_result),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="output"),
            patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            await worker._process_task(task, agent_def)

        assert task.task_id not in worker._context_cache

    @pytest.mark.asyncio
    async def test_cache_retained_on_task_failure(self):
        cfg = _make_config(context_files=["standards.md"])
        worker, agent_def = self._setup_worker_mocks(cfg)
        task = _make_task()
        context_result = _make_context_result()

        with (
            patch("agentharness.worker.resolve_context_files", return_value=context_result),
            patch("agentharness.worker.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("agent died")),
            patch("agentharness.worker.build_prompt", return_value="prompt"),
        ):
            with pytest.raises(RuntimeError):
                await worker._process_task(task, agent_def)

        assert task.task_id in worker._context_cache

    @pytest.mark.asyncio
    async def test_resolve_called_once_on_retry(self):
        cfg = _make_config(context_files=["standards.md"])
        worker, agent_def = self._setup_worker_mocks(cfg)
        task = _make_task()
        context_result = _make_context_result()

        # Simulate: first call fails (agent error), second succeeds
        with patch("agentharness.worker.resolve_context_files", return_value=context_result) as mock_resolve:
            with (
                patch("agentharness.worker.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("fail")),
                patch("agentharness.worker.build_prompt", return_value="prompt"),
            ):
                with pytest.raises(RuntimeError):
                    await worker._process_task(task, agent_def)

            # Second attempt (retry)
            with (
                patch("agentharness.worker.run_agent", new_callable=AsyncMock, return_value="output"),
                patch("agentharness.worker.dispatch_after_completion", new_callable=AsyncMock, return_value=None),
                patch("agentharness.worker.build_prompt", return_value="prompt"),
            ):
                await worker._process_task(task, agent_def)

        assert mock_resolve.call_count == 1
