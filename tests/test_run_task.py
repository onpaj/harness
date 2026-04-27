"""Unit tests for run_task helpers — task section parsing and context upload."""

import pytest
from unittest.mock import AsyncMock

from agentharness.run_task import _parse_task_sections, _upload_task_contexts


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
