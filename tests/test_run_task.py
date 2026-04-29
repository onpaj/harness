"""Unit tests for run_task helpers — task section parsing and context upload."""

from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.run_task import _parse_task_sections, _upload_task_contexts, run_task, _recover_task


class TestParseTaskSections:
    def test_parses_single_task(self):
        output = "### task: auth-module\nSome content here."
        sections = _parse_task_sections(output)
        assert "auth-module" in sections
        assert "Some content here." in sections["auth-module"]

    def test_parses_multiple_tasks(self):
        output = (
            "### task: auth-module\nAuth content.\n\n"
            "### task: user-api\nAPI content.\n"
        )
        sections = _parse_task_sections(output)
        assert set(sections) == {"auth-module", "user-api"}

    def test_each_section_contains_only_its_content(self):
        output = (
            "### task: task-a\nContent A.\n\n"
            "### task: task-b\nContent B.\n"
        )
        sections = _parse_task_sections(output)
        assert "Content B." not in sections["task-a"]
        assert "Content A." not in sections["task-b"]

    def test_normalises_spaces_to_hyphens(self):
        output = "### task: My Feature Task\nContent."
        sections = _parse_task_sections(output)
        assert "my-feature-task" in sections

    def test_case_insensitive_header(self):
        output = "### TASK: setup\nContent."
        sections = _parse_task_sections(output)
        assert "setup" in sections

    def test_empty_output_returns_empty_dict(self):
        assert _parse_task_sections("") == {}

    def test_output_without_task_headers_returns_empty(self):
        output = "# Implementation Plan\n\nSome intro text.\n\n## Phase 1\nDetails."
        assert _parse_task_sections(output) == {}

    def test_section_includes_its_header(self):
        output = "### task: setup\nDo the setup."
        sections = _parse_task_sections(output)
        assert sections["setup"].startswith("### task: setup")

    def test_preserves_section_order(self):
        output = (
            "### task: first\nA\n"
            "### task: second\nB\n"
            "### task: third\nC\n"
        )
        sections = _parse_task_sections(output)
        assert list(sections.keys()) == ["first", "second", "third"]


@pytest.mark.asyncio
class TestUploadTaskContexts:
    async def test_uploads_one_blob_per_task(self):
        store = AsyncMock()
        store.upload = AsyncMock()
        output = (
            "### task: auth\nAuth content.\n\n"
            "### task: api\nAPI content.\n"
        )

        paths = await _upload_task_contexts(store, "feat-99", output)

        assert store.upload.await_count == 2
        assert "auth" in paths
        assert "api" in paths

    async def test_returns_correct_blob_paths(self):
        store = AsyncMock()
        store.upload = AsyncMock()
        output = "### task: setup\nContent."

        paths = await _upload_task_contexts(store, "feat-42", output)

        assert paths["setup"] == "artifacts/feat-42/task-context/setup.md"

    async def test_empty_output_uploads_nothing(self):
        store = AsyncMock()
        store.upload = AsyncMock()

        paths = await _upload_task_contexts(store, "feat-01", "no task headers here")

        store.upload.assert_not_awaited()
        assert paths == {}


def _make_run_task_fixtures(storage_backend: str = "azure"):
    """Build common mock objects for run_task tests."""
    task_json = (
        '{"task_id": "t1", "feature_id": "feat-01", "queue_name": "dev-queue",'
        ' "input_artifacts": [], "output_artifact": "artifacts/feat-01/out.md",'
        ' "agent_role": "developer", "work_dir": null, "revision": 1}'
    )
    config = MagicMock()
    config.storage_backend = storage_backend
    config.queue_names.return_value = []
    config.agent_path_for_queue.return_value = MagicMock()

    mock_store = AsyncMock()
    mock_store.upload = AsyncMock()
    mock_store.close = AsyncMock()
    mock_store.commit_workdir_changes = AsyncMock(return_value=False)

    mock_state_mgr = AsyncMock()
    mock_state = MagicMock()
    mock_state.worktree_path = None
    mock_state.branch_name = None
    mock_state_mgr.get = AsyncMock(return_value=mock_state)
    mock_state_mgr.update = AsyncMock(return_value=mock_state)

    mock_agent_def = MagicMock()
    mock_agent_def.allowed_tools = []
    mock_agent_def.output_file_glob = None
    mock_agent_def.system_prompt = "You are a developer agent."
    mock_agent_def.context_files = []

    mock_run_result = MagicMock()
    mock_run_result.output = "## Status: DONE"
    mock_run_result.tokens = None

    return task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result


@pytest.mark.asyncio
class TestRecoverTask:
    """Verify _recover_task increments attempt count via history events."""

    def _make_state(self, task_id: str, requeued_count: int):
        from agentharness.models import FeatureState, FeatureStatus, HistoryEvent
        state = FeatureState(feature_id="feat-x")
        history = [
            HistoryEvent(event="task_requeued", task_id=task_id)
            for _ in range(requeued_count)
        ]
        return state.model_copy(update={"history": history})

    def _make_task(self, task_id: str):
        from agentharness.models import TaskMessage
        return TaskMessage(
            task_id=task_id,
            feature_id="feat-x",
            queue_name="analyst-queue",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/spec.r1.md",
            agent_role="analyst",
        )

    async def test_first_failure_requeues(self):
        task = self._make_task("feat-x-analyzing-1")
        state = self._make_state(task.task_id, requeued_count=0)

        state_mgr = AsyncMock()
        state_mgr.get = AsyncMock(return_value=state)
        state_mgr.update = AsyncMock(return_value=state)

        mock_queue = AsyncMock()
        all_queues = {"analyst-queue": mock_queue}

        await _recover_task(state_mgr, task, "analyst-queue", MagicMock(), all_queues, retry_limit=3)

        state_mgr.update.assert_awaited_once()
        mock_queue.send_task.assert_awaited_once_with(task)

    async def test_second_failure_requeues(self):
        task = self._make_task("feat-x-analyzing-1")
        state = self._make_state(task.task_id, requeued_count=1)

        state_mgr = AsyncMock()
        state_mgr.get = AsyncMock(return_value=state)
        state_mgr.update = AsyncMock(return_value=state)

        mock_queue = AsyncMock()
        all_queues = {"analyst-queue": mock_queue}

        await _recover_task(state_mgr, task, "analyst-queue", MagicMock(), all_queues, retry_limit=3)

        mock_queue.send_task.assert_awaited_once_with(task)

    async def test_exhausted_retries_marks_failed(self):
        task = self._make_task("feat-x-analyzing-1")
        # 2 prior requeues → attempts=3, 3 < 3 is False → mark failed
        state = self._make_state(task.task_id, requeued_count=2)

        state_mgr = AsyncMock()
        state_mgr.get = AsyncMock(return_value=state)
        state_mgr.update = AsyncMock(return_value=state)

        mock_queue = AsyncMock()
        all_queues = {"analyst-queue": mock_queue}

        await _recover_task(state_mgr, task, "analyst-queue", MagicMock(), all_queues, retry_limit=3)

        mock_queue.send_task.assert_not_awaited()
        state_mgr.update.assert_awaited_once()

    async def test_phase_agent_without_task_entry_loops_no_more(self):
        """Regression: phase agents with no TaskEntry used to loop forever at attempt 1."""
        task = self._make_task("feat-x-analyzing-1")
        # Simulate the old broken state: 5 requeued events already recorded
        state = self._make_state(task.task_id, requeued_count=5)

        state_mgr = AsyncMock()
        state_mgr.get = AsyncMock(return_value=state)
        state_mgr.update = AsyncMock(return_value=state)

        mock_queue = AsyncMock()
        all_queues = {"analyst-queue": mock_queue}

        await _recover_task(state_mgr, task, "analyst-queue", MagicMock(), all_queues, retry_limit=3)

        # With 5 prior events, attempts=6 >= 3, so it should mark failed not requeue
        mock_queue.send_task.assert_not_awaited()


@pytest.mark.asyncio
class TestRunTaskUsesStorageFactory:
    """Verify run_task uses factory functions and not BlobServiceClient directly."""

    @pytest.mark.parametrize("storage_backend", ["azure", "github"])
    async def test_uses_create_artifact_store(self, storage_backend: str):
        """run_task calls create_artifact_store regardless of backend."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures(storage_backend)
        )
        mock_store.get_work_dir = MagicMock(return_value=None)

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store) as mock_cas,
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr) as mock_csm,
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("dev-queue", task_json, config)

        mock_cas.assert_called_once_with(config, feature_id="feat-01")
        mock_csm.assert_called_once_with(config)

    async def test_no_direct_blob_service_client_import(self):
        """run_task module must not import BlobServiceClient at module level."""
        import agentharness.run_task as rt_module

        # The module should not hold a direct reference to BlobServiceClient
        assert "BlobServiceClient" not in dir(rt_module), (
            "BlobServiceClient was found in run_task module namespace — remove the direct import"
        )


@pytest.mark.asyncio
class TestOrphanTaskGuard:
    """When a developer/review task message arrives but its task_id is no longer
    in state.tasks (e.g. after a manual rollback), run_task must drop the message,
    emit a dropped_orphan_task audit event, and not run the agent."""

    async def test_drops_developer_message_when_task_id_missing(self):
        from agentharness.run_task import run_task as run_task_fn

        task_json = (
            '{"task_id": "feat-x-dev-old", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/impl/old.r1.md",'
            ' "agent_role": "developer", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []

        # State no longer contains the task_id from the message.
        mock_state_mgr = AsyncMock()
        mock_state = MagicMock()
        mock_state.worktree_path = None
        mock_state.branch_name = None
        mock_state.tasks = []  # rollback cleared everything
        mock_state_mgr.get = AsyncMock(return_value=mock_state)
        mock_state_mgr.update = AsyncMock(return_value=mock_state)

        mock_store = AsyncMock()
        mock_store.close = AsyncMock()

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.run_agent") as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion") as mock_dispatch,
        ):
            await run_task_fn("developer-queue", task_json, config)

        # Agent must NOT have been invoked
        mock_run_agent.assert_not_called()
        mock_dispatch.assert_not_called()

        # An audit event must have been written
        update_calls = mock_state_mgr.update.await_args_list
        assert len(update_calls) >= 1
        # The closure should produce an event named dropped_orphan_task — invoke it
        # against a real FeatureState to confirm.
        from agentharness.models import FeatureState
        probe_state = FeatureState(feature_id="feat-x")
        produced = update_calls[0].args[1](probe_state)
        assert any(e.event == "dropped_orphan_task" for e in produced.history)

    async def test_runs_normally_when_task_id_is_present(self):
        """Sanity: presence of the task_id in state.tasks does not trigger the guard."""
        from agentharness.models import FeatureState, TaskEntry, TaskStatus
        from agentharness.run_task import run_task as run_task_fn

        existing_task_id = "feat-x-dev-here"
        task_json = (
            f'{{"task_id": "{existing_task_id}", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/impl/here.r1.md",'
            ' "agent_role": "developer", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []
        config.agent_path_for_queue.return_value = MagicMock()

        state = FeatureState(feature_id="feat-x").with_tasks_added([
            TaskEntry(task_id=existing_task_id, phase="developing", status=TaskStatus.queued)
        ])

        mock_state_mgr = AsyncMock()
        mock_state_mgr.get = AsyncMock(return_value=state)
        mock_state_mgr.update = AsyncMock(return_value=state)

        mock_store = AsyncMock()
        mock_store.upload = AsyncMock()
        mock_store.close = AsyncMock()

        mock_agent_def = MagicMock()
        mock_agent_def.allowed_tools = []
        mock_agent_def.system_prompt = "x"
        mock_agent_def.context_files = []

        mock_run_result = MagicMock()
        mock_run_result.output = "## Status: DONE"
        mock_run_result.tokens = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result) as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task_fn("developer-queue", task_json, config)

        # Agent should have been invoked (no orphan)
        mock_run_agent.assert_called_once()

    async def test_does_not_apply_guard_to_phase_agent_messages(self):
        """Phase-level messages (no task_id in state.tasks) must still execute —
        phase agents do not have TaskEntry rows. We only skip dev/review messages
        whose task_id starts with the feature_id followed by '-dev-' or '-review-'."""
        from agentharness.models import FeatureState
        from agentharness.run_task import run_task as run_task_fn

        # Message uses the analyst-phase task_id pattern (no -dev-/-review-)
        task_json = (
            '{"task_id": "feat-x-analyzing-1", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/spec.r1.md",'
            ' "agent_role": "analyst", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []
        config.agent_path_for_queue.return_value = MagicMock()

        state = FeatureState(feature_id="feat-x")  # no tasks; that is normal for phase work

        mock_state_mgr = AsyncMock()
        mock_state_mgr.get = AsyncMock(return_value=state)
        mock_state_mgr.update = AsyncMock(return_value=state)

        mock_store = AsyncMock()
        mock_store.upload = AsyncMock()
        mock_store.close = AsyncMock()

        mock_agent_def = MagicMock()
        mock_agent_def.allowed_tools = []
        mock_agent_def.system_prompt = "x"
        mock_agent_def.context_files = []

        mock_run_result = MagicMock()
        mock_run_result.output = "spec content"
        mock_run_result.tokens = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result) as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task_fn("analyst-queue", task_json, config)

        mock_run_agent.assert_called_once()


@pytest.mark.asyncio
class TestRunTaskGetWorkDir:
    """Verify run_task handles both None and Path from get_work_dir correctly."""

    async def test_get_work_dir_none_skips_commit(self):
        """When get_work_dir returns None and neither allowed_tools nor output_file_glob is set, commit is not called."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("azure")
        )
        mock_store.get_work_dir = MagicMock(return_value=None)
        mock_agent_def.allowed_tools = []
        mock_agent_def.output_file_glob = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("dev-queue", task_json, config)

        mock_store.commit_workdir_changes.assert_not_awaited()

    async def test_get_work_dir_path_with_allowed_tools_calls_commit(self, tmp_path: Path):
        """When get_work_dir returns a Path and allowed_tools is set, commit_workdir_changes is called."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("github")
        )
        mock_store.get_work_dir = MagicMock(return_value=tmp_path)
        mock_store.commit_workdir_changes = AsyncMock(return_value=True)
        mock_agent_def.allowed_tools = ["bash", "read", "write"]
        mock_agent_def.output_file_glob = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("dev-queue", task_json, config)

        mock_store.commit_workdir_changes.assert_awaited_once()

    async def test_output_file_glob_triggers_commit(self, tmp_path: Path):
        """When output_file_glob is set (no allowed_tools), commit_workdir_changes is still called."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("github")
        )
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec content")
        mock_store.get_work_dir = MagicMock(return_value=tmp_path)
        mock_store.commit_workdir_changes = AsyncMock(return_value=True)
        mock_agent_def.allowed_tools = []
        mock_agent_def.output_file_glob = "spec.md"

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("analyst-queue", task_json, config)

        mock_store.commit_workdir_changes.assert_awaited_once()
        content = mock_store.upload.call_args[0][1]
        assert content == "# Spec content"

    async def test_get_work_dir_none_with_allowed_tools_still_calls_commit(self):
        """get_work_dir returning None doesn't prevent commit — commit is always called when allowed_tools is set."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("azure")
        )
        mock_store.get_work_dir = MagicMock(return_value=None)
        mock_store.commit_workdir_changes = AsyncMock(return_value=False)
        mock_agent_def.allowed_tools = ["bash", "read", "write"]
        mock_agent_def.output_file_glob = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("dev-queue", task_json, config)

        mock_store.commit_workdir_changes.assert_awaited_once()

    async def test_output_file_glob_triggers_commit(self, tmp_path: Path):
        """When output_file_glob is set (no allowed_tools), commit_workdir_changes is still called."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("github")
        )
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec content")
        mock_store.get_work_dir = MagicMock(return_value=tmp_path)
        mock_store.commit_workdir_changes = AsyncMock(return_value=True)
        mock_agent_def.allowed_tools = []
        mock_agent_def.output_file_glob = "spec.md"

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result),
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task("analyst-queue", task_json, config)

        mock_store.commit_workdir_changes.assert_awaited_once()
        content = mock_store.upload.call_args[0][1]
        assert content == "# Spec content"
