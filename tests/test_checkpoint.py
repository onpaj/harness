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
    from agentharness.models import PhaseCheckpoint
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
    from agentharness.models import PhaseCheckpoint
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
    from agentharness.models import TaskCheckpoint
    cp = cp.model_copy(update={"tasks": [
        TaskCheckpoint(name="a", status="completed"),
        TaskCheckpoint(name="b", status="completed"),
    ]})
    assert cp.all_tasks_complete() is True

def test_agent_definition_still_exists():
    # AgentDefinition must be kept for prompt_builder.py and brainstorm.py
    ad = AgentDefinition(id="analyst", model="claude-sonnet-4-6", phase="analyzing", system_prompt="You are an analyst.")
    assert ad.id == "analyst"
