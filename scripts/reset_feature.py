"""One-shot script: reset a feature's state back to 'brainstormed'."""
import asyncio
import sys
from datetime import UTC, datetime

# Ensure the package is importable when run from the repo root
sys.path.insert(0, ".")

from agentharness.config import load_config
from agentharness.github_state import GitHubStateManager
from agentharness.models import FeatureState, FeatureStatus, HistoryEvent, PipelineConfig


async def reset_to_brainstormed(feature_id: str) -> None:
    config = load_config()
    mgr = GitHubStateManager.from_config(config)

    def _reset(s: FeatureState) -> FeatureState:
        return s.model_copy(
            update={
                "status": FeatureStatus.brainstormed,
                "tasks": [],
                "phases": {},
                "config": PipelineConfig(),
                "worktree_path": None,
                "branch_name": None,
                "cleanup_warning": None,
                "updated_at": datetime.now(UTC),
                "history": [
                    *s.history,
                    HistoryEvent(
                        timestamp=datetime.now(UTC),
                        event="manual_state_change",
                        details="reset to brainstormed by operator",
                    ),
                ],
            }
        )

    new_state = await mgr.update(feature_id, _reset)
    print(f"Reset {feature_id!r} → {new_state.status.value}")
    print(f"Issue #{new_state.state_issue_number}")


if __name__ == "__main__":
    feature_id = sys.argv[1] if len(sys.argv) > 1 else "feat-tui-feature-state-change-dialog"
    asyncio.run(reset_to_brainstormed(feature_id))
