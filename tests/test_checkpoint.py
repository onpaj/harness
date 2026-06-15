# tests/test_checkpoint.py
from datetime import datetime, UTC
from agentharness.models import Checkpoint, PhaseCheckpoint, TaskCheckpoint, AgentDefinition

def test_checkpoint_defaults():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    assert cp.phases["analyzing"].status == "pending"
    assert cp.phases["analyzing"].updated_at is None
    assert cp.tasks == []
    assert cp.max_revisions == 3

def test_checkpoint_phase_names():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    # developing is included for display; next_pending_phase() skips it
    expected = {"analyzing", "architecting", "designing", "planning", "developing"}
    assert set(cp.phases.keys()) == expected

def test_task_checkpoint_defaults():
    t = TaskCheckpoint(name="setup-models")
    assert t.status == "pending"
    assert t.revision == 1
    assert t.updated_at is None

def test_next_pending_phase_skips_developing():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    # All pipeline phases done, developing pending
    cp = cp.model_copy(update={"phases": {
        "analyzing":    PhaseCheckpoint(status="completed"),
        "architecting": PhaseCheckpoint(status="completed"),
        "designing":    PhaseCheckpoint(status="completed"),
        "planning":     PhaseCheckpoint(status="completed"),
        "developing":   PhaseCheckpoint(status="pending"),
    }})
    # next_pending_phase must NOT return "developing"
    assert cp.next_pending_phase() is None

def test_next_pending_phase_returns_first_pending():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    cp = cp.model_copy(update={"phases": {
        "analyzing":    PhaseCheckpoint(status="completed"),
        "architecting": PhaseCheckpoint(status="pending"),
        "designing":    PhaseCheckpoint(status="pending"),
        "planning":     PhaseCheckpoint(status="pending"),
        "developing":   PhaseCheckpoint(status="pending"),
    }})
    assert cp.next_pending_phase() == "architecting"

def test_all_tasks_complete_false_when_empty():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    assert cp.all_tasks_complete() is False

def test_all_tasks_complete_true():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    cp = cp.model_copy(update={"tasks": [
        TaskCheckpoint(name="a", status="completed"),
        TaskCheckpoint(name="b", status="completed"),
    ]})
    assert cp.all_tasks_complete() is True

def test_all_tasks_complete_true_when_all_failed():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    cp = cp.model_copy(update={"tasks": [
        TaskCheckpoint(name="a", status="failed"),
        TaskCheckpoint(name="b", status="failed"),
    ]})
    assert cp.all_tasks_complete() is True

def test_all_tasks_complete_false_when_one_pending():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    cp = cp.model_copy(update={"tasks": [
        TaskCheckpoint(name="a", status="completed"),
        TaskCheckpoint(name="b", status="pending"),
    ]})
    assert cp.all_tasks_complete() is False

def test_agent_definition_still_exists():
    # AgentDefinition must be kept for prompt_builder.py and brainstorm.py
    ad = AgentDefinition(id="analyst", model="claude-sonnet-4-6", phase="analyzing", system_prompt="You are an analyst.")
    assert ad.id == "analyst"
    assert ad.context_files is None  # new field added in this task
    assert ad.max_turns == 20


import json
from agentharness.checkpoint import (
    init_checkpoint,
    load_checkpoint,
    update_phase,
    update_task,
    set_tasks,
    query_next,
    list_checkpoints,
)

def test_init_checkpoint_creates_file(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    state_file = tmp_path / "artifacts" / "feat-123" / "state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["feature_id"] == "feat-123"
    assert data["issue_number"] == 123

def test_init_checkpoint_idempotent(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    cp1 = load_checkpoint("feat-123", base_dir=tmp_path)
    init_checkpoint(123, base_dir=tmp_path)
    cp2 = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp1.created_at == cp2.created_at

def test_update_phase_sets_timestamp(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.phases["analyzing"].status == "completed"
    assert cp.phases["analyzing"].updated_at is not None

def test_set_tasks_populates_list(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models", "api-endpoints"], base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert len(cp.tasks) == 2
    assert cp.tasks[0].name == "setup-models"
    assert cp.tasks[1].status == "pending"

def test_update_task_sets_revision(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    update_task("feat-123", "setup-models", "in_progress", revision=2, base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.tasks[0].revision == 2

def test_update_task_without_revision_preserves_existing(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    update_task("feat-123", "setup-models", "in_progress", revision=2, base_dir=tmp_path)
    update_task("feat-123", "setup-models", "completed", base_dir=tmp_path)  # no revision
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.tasks[0].revision == 2  # preserved

def test_query_next_returns_pending_phase(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result == {"type": "phase", "name": "analyzing"}

def test_query_next_returns_task_after_all_phases_complete(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    for phase in ["analyzing", "architecting", "designing", "planning"]:
        update_phase("feat-123", phase, "completed", base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result == {"type": "task", "name": "setup-models", "revision": 1}

def test_query_next_returns_complete_when_all_tasks_done(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    for phase in ["analyzing", "architecting", "designing", "planning"]:
        update_phase("feat-123", phase, "completed", base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    update_task("feat-123", "setup-models", "completed", base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result == {"type": "complete"}

def test_atomic_write_produces_valid_json(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    state_file = tmp_path / "artifacts" / "feat-123" / "state.json"
    data = json.loads(state_file.read_text())
    assert data["phases"]["analyzing"]["status"] == "completed"

def test_list_checkpoints_empty(tmp_path):
    result = list_checkpoints(base_dir=tmp_path)
    assert result == []

def test_list_checkpoints_reads_all(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    init_checkpoint(456, base_dir=tmp_path)
    result = list_checkpoints(base_dir=tmp_path)
    assert len(result) == 2
    ids = {cp.feature_id for cp in result}
    assert ids == {"feat-123", "feat-456"}

def test_list_checkpoints_skips_corrupt(tmp_path):
    (tmp_path / "artifacts" / "feat-bad").mkdir(parents=True)
    (tmp_path / "artifacts" / "feat-bad" / "state.json").write_text("not json")
    result = list_checkpoints(base_dir=tmp_path)
    assert result == []
