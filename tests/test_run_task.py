"""Unit tests for run_task helpers — task section parsing and context upload."""

from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.run_task import _parse_task_sections, _upload_task_contexts, run_task


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
    mock_agent_def.system_prompt = "You are a developer agent."
    mock_agent_def.context_files = []

    mock_run_result = MagicMock()
    mock_run_result.output = "## Status: DONE"
    mock_run_result.tokens = None

    return task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result


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
class TestRunTaskGetWorkDir:
    """Verify run_task handles both None and Path from get_work_dir correctly."""

    async def test_get_work_dir_none_skips_commit(self):
        """When get_work_dir returns None, commit_workdir_changes is not called."""
        task_json, config, mock_store, mock_state_mgr, mock_agent_def, mock_run_result = (
            _make_run_task_fixtures("azure")
        )
        mock_store.get_work_dir = MagicMock(return_value=None)
        # allowed_tools is empty — commit should never be called regardless
        mock_agent_def.allowed_tools = []

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
