"""Unit tests for FeatureState model — worktree fields."""

import json

import pytest

from agentharness.models import FeatureState, FeatureStatus


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
