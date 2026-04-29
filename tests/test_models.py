"""Unit tests for FeatureState model — worktree fields."""

import json
import time

import pytest

from agentharness.models import FeatureState, FeatureStatus, TaskEntry, TaskStatus


def _make_state(feature_id: str = "feat-test") -> FeatureState:
    return FeatureState(feature_id=feature_id)


class TestFeatureStateWorktreeDefaults:
    def test_worktree_path_defaults_to_none(self):
        state = _make_state()
        assert state.worktree_path is None

    def test_cleanup_warning_defaults_to_none(self):
        state = _make_state()
        assert state.cleanup_warning is None


class TestWithWorktreePath:
    def test_returns_new_instance_with_path_set(self):
        state = _make_state()
        updated = state.with_worktree_path("/repo/.worktrees/feat-test")
        assert updated.worktree_path == "/repo/.worktrees/feat-test"

    def test_original_instance_unchanged(self):
        state = _make_state()
        state.with_worktree_path("/repo/.worktrees/feat-test")
        assert state.worktree_path is None

    def test_setting_same_value_is_noop(self):
        state = _make_state().with_worktree_path("/path/a")
        updated = state.with_worktree_path("/path/a")
        assert updated.worktree_path == "/path/a"

    def test_overwriting_with_different_value_raises(self):
        state = _make_state().with_worktree_path("/path/a")
        with pytest.raises(ValueError, match="immutability invariant"):
            state.with_worktree_path("/path/b")

    def test_other_fields_preserved(self):
        state = FeatureState(feature_id="feat-abc", status=FeatureStatus.developing)
        updated = state.with_worktree_path("/repo/.worktrees/feat-abc")
        assert updated.feature_id == "feat-abc"
        assert updated.status == FeatureStatus.developing


class TestWithCleanupWarning:
    def test_returns_new_instance_with_warning_set(self):
        state = _make_state()
        updated = state.with_cleanup_warning("removal failed: dirty working tree")
        assert updated.cleanup_warning == "removal failed: dirty working tree"

    def test_original_instance_unchanged(self):
        state = _make_state()
        state.with_cleanup_warning("some warning")
        assert state.cleanup_warning is None

    def test_other_fields_preserved(self):
        state = FeatureState(feature_id="feat-abc", status=FeatureStatus.done)
        updated = state.with_cleanup_warning("cleanup error")
        assert updated.feature_id == "feat-abc"
        assert updated.status == FeatureStatus.done


class TestLegacyDeserialization:
    def test_state_json_without_new_fields_deserializes_cleanly(self):
        legacy_json = json.dumps(
            {
                "feature_id": "feat-legacy",
                "status": "done",
            }
        )
        state = FeatureState.model_validate_json(legacy_json)
        assert state.feature_id == "feat-legacy"
        assert state.worktree_path is None
        assert state.cleanup_warning is None

    def test_state_json_with_null_new_fields_deserializes_cleanly(self):
        full_json = json.dumps(
            {
                "feature_id": "feat-new",
                "status": "developing",
                "worktree_path": None,
                "cleanup_warning": None,
            }
        )
        state = FeatureState.model_validate_json(full_json)
        assert state.worktree_path is None
        assert state.cleanup_warning is None

    def test_state_json_with_worktree_path_set_deserializes(self):
        json_str = json.dumps(
            {
                "feature_id": "feat-wt",
                "status": "developing",
                "worktree_path": "/repo/.worktrees/feat-wt",
            }
        )
        state = FeatureState.model_validate_json(json_str)
        assert state.worktree_path == "/repo/.worktrees/feat-wt"


class TestWithTasksCleared:
    def _state_with_tasks(self) -> FeatureState:
        return FeatureState(feature_id="feat-test").with_tasks_added([
            TaskEntry(task_id="feat-test-dev-a", phase="developing", status=TaskStatus.completed),
            TaskEntry(task_id="feat-test-dev-b", phase="developing", status=TaskStatus.queued),
        ])

    def test_returns_state_with_empty_tasks(self):
        state = self._state_with_tasks()
        cleared = state.with_tasks_cleared()
        assert cleared.tasks == []

    def test_original_instance_is_unchanged(self):
        state = self._state_with_tasks()
        state.with_tasks_cleared()
        assert len(state.tasks) == 2

    def test_other_fields_preserved(self):
        state = FeatureState(
            feature_id="feat-abc", status=FeatureStatus.developing
        ).with_tasks_added([
            TaskEntry(
                task_id="t1", phase="developing"
            )
        ])
        cleared = state.with_tasks_cleared()
        assert cleared.feature_id == "feat-abc"
        assert cleared.status == FeatureStatus.developing
        assert cleared.tasks == []

    def test_updated_at_changes(self):
        state = self._state_with_tasks()
        original_updated = state.updated_at
        time.sleep(0.001)
        cleared = state.with_tasks_cleared()
        assert cleared.updated_at > original_updated

    def test_returns_empty_when_already_empty(self):
        state = FeatureState(feature_id="feat-empty")
        assert state.tasks == []
        cleared = state.with_tasks_cleared()
        assert cleared.tasks == []


class TestQuestioningEnumValue:
    def test_questioning_is_a_valid_status(self):
        assert FeatureStatus("questioning") == FeatureStatus.questioning

    def test_questioning_serialises_to_string(self):
        state = FeatureState(feature_id="feat-q", status=FeatureStatus.questioning)
        payload = state.model_dump_json()
        assert '"status":"questioning"' in payload

    def test_questioning_round_trips_through_json(self):
        state = FeatureState(feature_id="feat-q", status=FeatureStatus.questioning)
        restored = FeatureState.model_validate_json(state.model_dump_json())
        assert restored.status == FeatureStatus.questioning


class TestPipelineConfigAnalystFields:
    def test_defaults(self):
        from agentharness.models import PipelineConfig
        cfg = PipelineConfig()
        assert cfg.max_analyst_iterations == 2
        assert cfg.current_analyst_iteration == 0

    def test_explicit_values(self):
        from agentharness.models import PipelineConfig
        cfg = PipelineConfig(max_analyst_iterations=5, current_analyst_iteration=3)
        assert cfg.max_analyst_iterations == 5
        assert cfg.current_analyst_iteration == 3

    def test_zero_max_iterations_allowed(self):
        from agentharness.models import PipelineConfig
        cfg = PipelineConfig(max_analyst_iterations=0)
        assert cfg.max_analyst_iterations == 0

    def test_negative_max_iterations_rejected(self):
        from agentharness.models import PipelineConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PipelineConfig(max_analyst_iterations=-1)

    def test_negative_current_iteration_rejected(self):
        from agentharness.models import PipelineConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PipelineConfig(current_analyst_iteration=-1)

    def test_legacy_state_json_without_new_fields_deserializes(self):
        from agentharness.models import PipelineConfig
        legacy_cfg_json = '{"max_revisions": 3, "current_revision_round": 0}'
        cfg = PipelineConfig.model_validate_json(legacy_cfg_json)
        assert cfg.max_analyst_iterations == 2
        assert cfg.current_analyst_iteration == 0


class TestWithAnalystIterationIncremented:
    def _state(self, current: int = 0) -> FeatureState:
        from agentharness.models import PipelineConfig
        return FeatureState(
            feature_id="feat-it",
            config=PipelineConfig(current_analyst_iteration=current),
        )

    def test_increments_counter_by_one(self):
        state = self._state(current=0)
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.current_analyst_iteration == 1

    def test_subsequent_increment_continues(self):
        state = self._state(current=1)
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.current_analyst_iteration == 2

    def test_original_state_unchanged(self):
        state = self._state(current=0)
        state.with_analyst_iteration_incremented()
        assert state.config.current_analyst_iteration == 0

    def test_max_iterations_preserved(self):
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-it",
            config=PipelineConfig(max_analyst_iterations=5, current_analyst_iteration=2),
        )
        updated = state.with_analyst_iteration_incremented()
        assert updated.config.max_analyst_iterations == 5
        assert updated.config.current_analyst_iteration == 3

    def test_other_fields_preserved(self):
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-it",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        updated = state.with_analyst_iteration_incremented()
        assert updated.feature_id == "feat-it"
        assert updated.status == FeatureStatus.questioning

    def test_updated_at_advances(self):
        from datetime import UTC, datetime
        state = self._state(current=0)
        state = state.model_copy(update={"updated_at": datetime.now(UTC)})
        original = state.updated_at
        time.sleep(0.001)
        updated = state.with_analyst_iteration_incremented()
        assert updated.updated_at > original
