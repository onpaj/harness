"""Tests for tui.py checkpoint-based monitoring functions."""

from pathlib import Path
import pytest
from agentharness.tui import _load_all_checkpoints, _overall_status, _phase_summary, _task_summary
from agentharness.checkpoint import init_checkpoint, update_phase, update_task, set_tasks


def test_load_all_checkpoints_empty(tmp_path):
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert result == []


def test_load_all_checkpoints_reads_state_files(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    init_checkpoint(456, base_dir=tmp_path)
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert len(result) == 2
    ids = {cp.feature_id for cp in result}
    assert ids == {"feat-123", "feat-456"}


def test_load_all_checkpoints_skips_corrupt(tmp_path):
    (tmp_path / "artifacts" / "feat-bad").mkdir(parents=True)
    (tmp_path / "artifacts" / "feat-bad" / "state.json").write_text("not json")
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert result == []


def test_overall_status_pending_when_fresh(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    cp = _load_all_checkpoints(base_dir=tmp_path)[0]
    assert _overall_status(cp) == "pending"


def test_overall_status_running_when_phase_in_progress(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "in_progress", base_dir=tmp_path)
    cp = _load_all_checkpoints(base_dir=tmp_path)[0]
    assert _overall_status(cp) == "running"


def test_overall_status_failed_when_phase_failed(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "failed", base_dir=tmp_path)
    cp = _load_all_checkpoints(base_dir=tmp_path)[0]
    assert _overall_status(cp) == "failed"


def test_task_summary_dash_when_no_tasks(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    cp = _load_all_checkpoints(base_dir=tmp_path)[0]
    assert _task_summary(cp) == "—"


def test_task_summary_shows_completed_count(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["a", "b", "c"], base_dir=tmp_path)
    update_task("feat-123", "a", "completed", base_dir=tmp_path)
    cp = _load_all_checkpoints(base_dir=tmp_path)[0]
    assert _task_summary(cp) == "1/3"
