"""Label name constants for the GitHub backend.

All GitHub label strings used across the GitHub backend are defined here
to prevent typos and provide a single source of truth.
"""

from agentharness.models import FeatureStatus

# ---------------------------------------------------------------------------
# Feature-level status labels
# ---------------------------------------------------------------------------

FEAT_ANALYZING = "feat:analyzing"
FEAT_ARCHITECTING = "feat:architecting"
FEAT_DESIGNING = "feat:designing"
FEAT_PLANNING = "feat:planning"
FEAT_DEVELOPING = "feat:developing"
FEAT_REVIEWING = "feat:reviewing"
FEAT_DEV_REVISION = "feat:dev_revision"
FEAT_DONE = "feat:done"
FEAT_FAILED = "feat:failed"

FEAT_STATUS_LABELS: frozenset[str] = frozenset({
    FEAT_ANALYZING,
    FEAT_ARCHITECTING,
    FEAT_DESIGNING,
    FEAT_PLANNING,
    FEAT_DEVELOPING,
    FEAT_REVIEWING,
    FEAT_DEV_REVISION,
    FEAT_DONE,
    FEAT_FAILED,
})

# ---------------------------------------------------------------------------
# Task state labels
# ---------------------------------------------------------------------------

STATE_QUEUED = "state:queued"
STATE_IN_PROGRESS = "state:in-progress"
STATE_COMPLETED = "state:completed"
STATE_FAILED = "state:failed"
STATE_DEAD_LETTER = "state:dead-letter"
STATE_BLOCKED = "state:blocked"

TASK_STATE_LABELS: frozenset[str] = frozenset({
    STATE_QUEUED,
    STATE_IN_PROGRESS,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_DEAD_LETTER,
    STATE_BLOCKED,
})

# ---------------------------------------------------------------------------
# Queue routing labels
# ---------------------------------------------------------------------------

QUEUE_ANALYST = "queue:analyst"
QUEUE_ARCHITECT = "queue:architect"
QUEUE_DESIGNER = "queue:designer"
QUEUE_PLANNER = "queue:planner"
QUEUE_DEVELOPER = "queue:developer"
QUEUE_REVIEWER = "queue:reviewer"

QUEUE_NAME_TO_LABEL: dict[str, str] = {
    "analyst-queue": QUEUE_ANALYST,
    "architect-queue": QUEUE_ARCHITECT,
    "designer-queue": QUEUE_DESIGNER,
    "planner-queue": QUEUE_PLANNER,
    "developer-queue": QUEUE_DEVELOPER,
    "review-queue": QUEUE_REVIEWER,
}

LABEL_TO_QUEUE_NAME: dict[str, str] = {v: k for k, v in QUEUE_NAME_TO_LABEL.items()}

# ---------------------------------------------------------------------------
# Marker and claim labels
# ---------------------------------------------------------------------------

FEATURE_MARKER = "agentharness-feature"
IMPLEMENT_LABEL = "implement"

CLAIMED_BY_PREFIX = "claimed-by:"


def claimed_by_label(worker_id: str) -> str:
    """Return the claim label for a given worker ID."""
    return f"{CLAIMED_BY_PREFIX}{worker_id}"


def is_claimed_by_label(label: str) -> bool:
    """Return True if the label is a claimed-by label."""
    return label.startswith(CLAIMED_BY_PREFIX)


# ---------------------------------------------------------------------------
# FeatureStatus <-> feat:* label round-trip mappings
# ---------------------------------------------------------------------------

FEATURE_STATUS_TO_LABEL: dict[FeatureStatus, str] = {
    FeatureStatus.analyzing: FEAT_ANALYZING,
    FeatureStatus.architecting: FEAT_ARCHITECTING,
    FeatureStatus.designing: FEAT_DESIGNING,
    FeatureStatus.planning: FEAT_PLANNING,
    FeatureStatus.developing: FEAT_DEVELOPING,
    FeatureStatus.reviewing: FEAT_REVIEWING,
    FeatureStatus.dev_revision: FEAT_DEV_REVISION,
    FeatureStatus.done: FEAT_DONE,
    FeatureStatus.failed: FEAT_FAILED,
}

LABEL_TO_FEATURE_STATUS: dict[str, FeatureStatus] = {
    v: k for k, v in FEATURE_STATUS_TO_LABEL.items()
}
