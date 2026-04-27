"""Issue-label state manager for the GitHub backend.

Feature state is persisted as:
  - A GitHub issue whose labels carry the current FeatureStatus.
  - A fenced ``agentharness-state`` block in the issue body that contains
    the full ``FeatureState`` JSON.

This implements the ``StateBackend`` protocol defined in
``agentharness.storage_protocol``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Callable

from agentharness.github_labels import (
    FEATURE_MARKER,
    FEATURE_STATUS_TO_LABEL,
    FEAT_STATUS_LABELS,
    LABEL_TO_FEATURE_STATUS,
)
from agentharness.models import FeatureState, FeatureStatus

if TYPE_CHECKING:
    from agentharness.config import Config
    from agentharness.github_client import GitHubClient

log = logging.getLogger(__name__)

_STATE_FENCE_OPEN = "```agentharness-state"
_STATE_FENCE_CLOSE = "```"
_STATE_BLOCK_RE = re.compile(
    r"```agentharness-state\s*\n(.*?)\n```",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_state_json(body: str) -> str:
    """Extract the JSON string from the fenced agentharness-state block."""
    match = _STATE_BLOCK_RE.search(body)
    if not match:
        raise ValueError("No agentharness-state fenced block found in issue body")
    return match.group(1).strip()


def _build_state_comment(state: FeatureState) -> str:
    """Build the comment body containing the serialized FeatureState JSON."""
    json_blob = state.model_dump_json()
    return f"{_STATE_FENCE_OPEN}\n{json_blob}\n{_STATE_FENCE_CLOSE}\n"


def _feature_label(feature_id: str) -> str:
    return f"feature:{feature_id}"


def _feature_issue_title(feature_id: str) -> str:
    """Format: 'feature: Humanized Name' derived from the feature_id slug."""
    # Strip leading type prefix (feat-, fix-, epic-) to get the name part
    for prefix in ("feat-", "fix-", "epic-"):
        if feature_id.startswith(prefix):
            issue_type = prefix.rstrip("-")
            name = feature_id[len(prefix):].replace("-", " ").title()
            return f"{issue_type}: {name}"
    name = feature_id.replace("-", " ").title()
    return f"feature: {name}"


def _status_from_issue_labels(issue: dict) -> FeatureStatus | None:
    """Return the FeatureStatus inferred from the issue's feat:* labels."""
    for label_obj in issue.get("labels", []):
        label_name = label_obj["name"]
        if label_name in FEAT_STATUS_LABELS:
            return LABEL_TO_FEATURE_STATUS.get(label_name)
    return None


def _feature_id_from_issue_labels(issue: dict) -> str | None:
    """Extract the feature_id from a ``feature:{feature_id}`` label."""
    for label_obj in issue.get("labels", []):
        label_name = label_obj["name"]
        if label_name.startswith("feature:"):
            return label_name[len("feature:"):]
    return None


# ---------------------------------------------------------------------------
# GitHubStateManager
# ---------------------------------------------------------------------------


class GitHubStateManager:
    """StateBackend implementation backed by GitHub Issues."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager:
        from agentharness.github_client import GitHubClient

        return cls(client=GitHubClient.from_config(config))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_issue(self, feature_id: str) -> tuple[dict, int]:
        """Search for the parent issue and return (issue_dict, issue_number).

        Raises ``KeyError`` if no issue is found.
        """
        query = (
            f"label:{_feature_label(feature_id)} "
            f"repo:{self._client.owner}/{self._client.repo}"
        )
        items = await self._client.search_issues(query)
        if not items:
            raise KeyError(f"No state found for feature {feature_id!r}")
        return items[0], items[0]["number"]

    async def _get_state_comment(self, issue_number: int) -> dict:
        """Return the first comment on the issue (which holds the state JSON)."""
        comments = await self._client.list_comments(issue_number)
        if not comments:
            raise ValueError(f"No state comment found on issue #{issue_number}")
        return comments[0]

    async def _state_from_issue(self, issue: dict) -> FeatureState:
        """Parse a FeatureState from the issue's first comment, overriding status from labels."""
        comment = await self._get_state_comment(issue["number"])
        json_str = _extract_state_json(comment["body"])
        state = FeatureState.model_validate_json(json_str)

        # Labels are the authoritative source of truth for status.
        status_from_label = _status_from_issue_labels(issue)
        if status_from_label is not None and status_from_label != state.status:
            state = state.model_copy(update={"status": status_from_label})

        return state

    # ------------------------------------------------------------------
    # StateBackend protocol
    # ------------------------------------------------------------------

    async def create(self, state: FeatureState, brief_content: str = "") -> None:
        """Create a GitHub issue representing the feature's initial state.

        The issue body is set to the brief document so it is human-readable.
        The serialized FeatureState JSON is stored in the first comment.
        """
        feat_label = _feature_label(state.feature_id)
        await self._client.ensure_label(feat_label, color="0075ca")

        status_label = FEATURE_STATUS_TO_LABEL[state.status]
        title = _feature_issue_title(state.feature_id)

        issue = await self._client.create_issue(
            title=title,
            body=brief_content,
            labels=[FEATURE_MARKER, feat_label, status_label],
        )
        await self._client.create_comment(issue["number"], _build_state_comment(state))
        log.debug("Created state issue for feature %s", state.feature_id)

    async def get(self, feature_id: str) -> FeatureState:
        """Fetch and reconstruct the FeatureState for the given feature_id."""
        issue, _ = await self._find_issue(feature_id)
        return await self._state_from_issue(issue)

    async def update(
        self,
        feature_id: str,
        updater: Callable[[FeatureState], FeatureState],
    ) -> FeatureState:
        """Apply *updater* to the current state and persist the result.

        Always rewrites the issue body. If the status changed, swaps the
        ``feat:*`` label on the issue.
        """
        issue, issue_number = await self._find_issue(feature_id)
        current = await self._state_from_issue(issue)
        new_state = updater(current)

        # Swap status labels only when the status actually changed.
        if new_state.status != current.status:
            old_label = FEATURE_STATUS_TO_LABEL[current.status]
            new_label = FEATURE_STATUS_TO_LABEL[new_state.status]
            await self._client.add_labels(issue_number, [new_label])
            await self._client.remove_label(issue_number, old_label)

        comment = await self._get_state_comment(issue_number)
        await self._client.update_comment(comment["id"], _build_state_comment(new_state))

        log.debug(
            "Updated state issue for feature %s (status: %s → %s)",
            feature_id,
            current.status.value,
            new_state.status.value,
        )
        return new_state

    async def set_worktree_path(self, feature_id: str, worktree_path: str) -> None:
        """Persist a worktree path into the feature state."""
        await self.update(
            feature_id,
            lambda s: s.with_worktree_path(worktree_path),
        )

    async def set_cleanup_warning(self, feature_id: str, message: str) -> None:
        """Persist a cleanup warning message into the feature state."""
        await self.update(
            feature_id,
            lambda s: s.with_cleanup_warning(message),
        )

    async def list_features(self) -> list[tuple[str, int]]:
        """Return all known features as ``(feature_id, issue_number)`` pairs.

        Results are sorted by issue number descending (newest first).
        """
        query = (
            f"label:{FEATURE_MARKER} "
            f"repo:{self._client.owner}/{self._client.repo}"
        )
        items = await self._client.search_issues(query, order="desc")

        results: list[tuple[str, int]] = []
        for issue in items:
            feature_id = _feature_id_from_issue_labels(issue)
            if feature_id is None:
                log.warning(
                    "Issue #%d has %s label but no feature:* label — skipping",
                    issue["number"],
                    FEATURE_MARKER,
                )
                continue
            results.append((feature_id, issue["number"]))

        results.sort(key=lambda pair: pair[1], reverse=True)
        return results
