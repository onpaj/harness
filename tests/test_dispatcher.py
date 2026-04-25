"""Unit tests for dispatcher — state transitions, parsing, serial dispatch."""

import pytest

from agentharness.dispatcher import (
    _parse_review_result,
    _parse_task_list,
    _fallback_developer_task,
)
from agentharness.models import FeatureState, TaskEntry, TaskStatus


class TestParseTaskList:
    def test_extracts_single_task(self):
        design = "### task: auth-module\nImplement JWT auth.\n"
        tasks = _parse_task_list(design, "feat-42")
        assert len(tasks) == 1
        assert tasks[0].task_id == "feat-42-dev-auth-module"
        assert "feat-42-dev-auth-module" in tasks[0].task_id
        assert "JWT auth" in tasks[0].context

    def test_extracts_multiple_tasks(self):
        design = (
            "### task: auth-module\nAuth task.\n\n"
            "### task: user-api\nAPI task.\n\n"
            "### task: ui-login\nUI task.\n"
        )
        tasks = _parse_task_list(design, "feat-test")
        assert len(tasks) == 3
        assert tasks[0].task_id == "feat-test-dev-auth-module"
        assert tasks[1].task_id == "feat-test-dev-user-api"
        assert tasks[2].task_id == "feat-test-dev-ui-login"

    def test_returns_empty_list_when_no_tasks(self):
        tasks = _parse_task_list("No tasks here.", "feat-test")
        assert tasks == []

    def test_task_name_normalised_to_kebab_case(self):
        design = "### task: My Complex Task Name\nDo things.\n"
        tasks = _parse_task_list(design, "feat-test")
        assert tasks[0].task_id == "feat-test-dev-my-complex-task-name"

    def test_task_includes_correct_input_artifacts(self):
        design = "### task: foo\nDo foo.\n"
        tasks = _parse_task_list(design, "feat-99")
        artifacts = tasks[0].input_artifacts
        assert any("spec" in a for a in artifacts)
        assert any("arch-review" in a for a in artifacts)
        assert any("design" in a for a in artifacts)

    def test_output_artifact_uses_revision_1(self):
        design = "### task: bar\nDo bar.\n"
        tasks = _parse_task_list(design, "feat-99")
        assert "r1" in tasks[0].output_artifact


class TestParseReviewResult:
    def test_all_pass_returns_empty(self):
        review = (
            "## Review Result: PASS\n\n"
            "### task: auth-module\n**Status:** PASS\n\n"
            "### task: user-api\n**Status:** PASS\n"
        )
        failed = _parse_review_result(review)
        assert failed == {}

    def test_identifies_failing_tasks(self):
        review = (
            "## Review Result: REVISION_NEEDED\n\n"
            "### task: auth-module\n"
            "**Status:** REVISION_NEEDED\n"
            "**Issues:**\n- Missing rate limiting\n- No tests\n\n"
            "### task: user-api\n**Status:** PASS\n"
        )
        failed = _parse_review_result(review)
        assert "auth-module" in failed
        assert "user-api" not in failed
        assert "Missing rate limiting" in failed["auth-module"]

    def test_multiple_failing_tasks(self):
        review = (
            "### task: task-one\n**Status:** REVISION_NEEDED\n**Issues:**\n- Issue A\n\n"
            "### task: task-two\n**Status:** REVISION_NEEDED\n**Issues:**\n- Issue B\n"
        )
        failed = _parse_review_result(review)
        assert len(failed) == 2
        assert "task-one" in failed
        assert "task-two" in failed


class TestFallbackDeveloperTask:
    def test_creates_valid_task(self):
        task = _fallback_developer_task("feat-99")
        assert task.feature_id == "feat-99"
        assert task.agent_role == "developer"
        assert task.output_artifact.endswith(".r1.md")


class TestFeatureStateHelpers:
    def _state_with_tasks(self, statuses: list[str]) -> FeatureState:
        tasks = [
            TaskEntry(
                task_id=f"feat-test-dev-{i}",
                phase="developing",
                status=TaskStatus(s),
            )
            for i, s in enumerate(statuses)
        ]
        state = FeatureState(feature_id="feat-test")
        return state.with_tasks_added(tasks)

    def test_all_tasks_complete_when_all_done(self):
        state = self._state_with_tasks(["completed", "completed"])
        assert state.all_tasks_complete("developing") is True

    def test_not_all_complete_when_one_in_progress(self):
        state = self._state_with_tasks(["completed", "in_progress"])
        assert state.all_tasks_complete("developing") is False

    def test_not_all_complete_when_no_tasks(self):
        state = FeatureState(feature_id="feat-empty")
        assert state.all_tasks_complete("developing") is False

    def test_with_task_update_is_immutable(self):
        state = self._state_with_tasks(["queued"])
        task_id = state.tasks[0].task_id
        updated = state.with_task_update(task_id, status=TaskStatus.completed)
        assert state.tasks[0].status == TaskStatus.queued
        assert updated.tasks[0].status == TaskStatus.completed

    def test_all_tasks_complete_when_one_failed(self):
        state = self._state_with_tasks(["completed", "failed"])
        assert state.all_tasks_complete("developing") is True

    def test_not_all_complete_when_pending_remains(self):
        state = self._state_with_tasks(["completed", "pending"])
        assert state.all_tasks_complete("developing") is False

    def test_next_pending_task_returns_first_pending(self):
        state = self._state_with_tasks(["completed", "pending", "pending"])
        next_task = state.next_pending_task("developing")
        assert next_task is not None
        assert next_task.task_id == "feat-test-dev-1"

    def test_next_pending_task_returns_none_when_none_pending(self):
        state = self._state_with_tasks(["completed", "completed"])
        assert state.next_pending_task("developing") is None

    def test_next_pending_task_ignores_other_phases(self):
        tasks = [
            TaskEntry(task_id="feat-test-review-0", phase="reviewing", status=TaskStatus.pending),
        ]
        state = FeatureState(feature_id="feat-test").with_tasks_added(tasks)
        assert state.next_pending_task("developing") is None
