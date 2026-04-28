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


def parse_state_from_issue(issue: dict) -> FeatureState | None:
    """Parse a FeatureState from a GitHub issue dict, or return None on failure."""
    import json as _json

    body = issue.get("body") or ""
    try:
        raw = _extract_state_json(body)
        return FeatureState.model_validate(_json.loads(raw))
    except Exception:
        return None


def _build_state_block(state: FeatureState) -> str:
    json_blob = state.model_dump_json()
    return f"{_STATE_FENCE_OPEN}\n{json_blob}\n{_STATE_FENCE_CLOSE}"


def _replace_state_block(body: str, state: FeatureState) -> str:
    """Replace the state block in *body*, or append it if absent."""
    new_block = _build_state_block(state)
    if _STATE_BLOCK_RE.search(body):
        return _STATE_BLOCK_RE.sub(new_block, body)
    return f"{body}\n\n{new_block}\n"


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


def _feature_id_from_issue(issue: dict) -> str | None:
    """Extract the feature_id from the agentharness-state JSON block in the issue body."""
    state = parse_state_from_issue(issue)
    return state.feature_id if state else None


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

        Fetches all agentharness-feature issues and filters in-memory by
        feature_id parsed from the state JSON body.

        Raises ``KeyError`` if no issue is found.
        """
        items = await self._client.list_issues(labels=[FEATURE_MARKER])
        for issue in items:
            if _feature_id_from_issue(issue) == feature_id:
                return issue, issue["number"]
        raise KeyError(f"No state found for feature {feature_id!r}")

    async def _get_state_comment(self, issue_number: int) -> dict:
        """Return the first comment on the issue (which holds the state JSON)."""
        comments = await self._client.list_comments(issue_number)
        if not comments:
            raise ValueError(f"No state comment found on issue #{issue_number}")
        return comments[0]

    async def _state_from_issue(self, issue: dict) -> FeatureState:
        """Parse FeatureState from issue body; fall back to first comment for legacy issues."""
        state = parse_state_from_issue(issue)
        if state is None:
            # Legacy: state stored in first comment
            comment = await self._get_state_comment(issue["number"])
            json_str = _extract_state_json(comment["body"])
            state = FeatureState.model_validate_json(json_str)

        status_from_label = _status_from_issue_labels(issue)
        if status_from_label is not None and status_from_label != state.status:
            state = state.model_copy(update={"status": status_from_label})
        return state

    # ------------------------------------------------------------------
    # StateBackend protocol
    # ------------------------------------------------------------------

    async def create(self, state: FeatureState, brief_content: str = "") -> None:
        """Create a GitHub issue representing the feature's initial state.

        The issue body contains the brief content followed by the fenced
        agentharness-state block holding the serialized FeatureState JSON.
        """
        status_label = FEATURE_STATUS_TO_LABEL[state.status]
        await self._client.ensure_labels([FEATURE_MARKER, status_label], color="0075ca")

        title = _feature_issue_title(state.feature_id)
        body = _replace_state_block(brief_content, state)
        issue = await self._client.create_issue(
            title=title,
            body=body,
            labels=[FEATURE_MARKER, status_label],
        )
        issue_number: int = issue["number"]
        updated = state.model_copy(update={"state_issue_number": issue_number})
        await self._client.update_issue(issue_number, body=_replace_state_block(brief_content, updated))
        log.debug("Created state issue #%d for feature %s", issue_number, state.feature_id)

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

        if new_state.status != current.status:
            old_label = FEATURE_STATUS_TO_LABEL[current.status]
            new_label = FEATURE_STATUS_TO_LABEL[new_state.status]
            await self._client.add_labels(issue_number, [new_label])
            await self._client.remove_label(issue_number, old_label)

        new_body = _replace_state_block(issue.get("body") or "", new_state)
        await self._client.update_issue(issue_number, body=new_body)

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
        items = await self._client.list_issues(labels=[FEATURE_MARKER], direction="desc")

        seen: dict[str, int] = {}  # feature_id -> highest issue_number
        for issue in items:
            feature_id = _feature_id_from_issue(issue)
            if feature_id is None:
                log.warning(
                    "Issue #%d has %s label but no parseable state JSON — skipping",
                    issue["number"],
                    FEATURE_MARKER,
                )
                continue
            issue_number: int = issue["number"]
            if feature_id not in seen or issue_number > seen[feature_id]:
                seen[feature_id] = issue_number

        results = sorted(seen.items(), key=lambda pair: pair[1], reverse=True)
        return results
