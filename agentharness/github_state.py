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


def extract_brief_from_issue_body(body: str) -> str:
    """Return the brief text from an issue body (everything before the state block)."""
    return _STATE_BLOCK_RE.sub("", body).strip()


def parse_state_from_issue(issue: dict) -> FeatureState | None:
    """Parse a FeatureState from a GitHub issue dict, or return None on failure.

    .. deprecated::
        Prefer ``GitHubStateManager._parse_state_from_issue`` for new code.
        # TODO: observer.py will be updated to use GitHubStateManager directly
        # in the observer refactor task; at that point this shim can be removed.
    """
    return GitHubStateManager._parse_state_from_issue(issue)


def _build_state_block(state: FeatureState) -> str:
    json_blob = state.model_dump_json()
    return f"{_STATE_FENCE_OPEN}\n{json_blob}\n{_STATE_FENCE_CLOSE}"


def _replace_state_block(body: str, state: FeatureState) -> str:
    """Replace the state block in *body*, or append it if absent."""
    new_block = _build_state_block(state)
    if _STATE_BLOCK_RE.search(body):
        return _STATE_BLOCK_RE.sub(new_block, body)
    return f"{body}\n\n{new_block}\n"


def _feature_label(feature_id: str) -> str:
    """Return the per-feature GitHub label name for a given feature_id."""
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


def _feature_id_from_issue(issue: dict) -> str | None:
    """Extract the feature_id from the agentharness-state JSON block in the issue body."""
    state = parse_state_from_issue(issue)
    return state.feature_id if state else None


# ---------------------------------------------------------------------------
# GitHubStateManager
# ---------------------------------------------------------------------------


class GitHubStateManager:
    """StateBackend implementation backed by GitHub Issues."""

    def __init__(
        self,
        client: GitHubClient,
        *,
        feature_marker: str,
    ) -> None:
        self._client = client
        self._feature_marker = feature_marker

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager:
        from agentharness.github_client import GitHubClient

        return cls(
            client=GitHubClient.from_config(config),
            feature_marker=config.github.feature_marker,
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_state_from_issue(issue: dict) -> FeatureState | None:
        """Parse a FeatureState from a GitHub issue dict, or None on failure."""
        import json as _json
        body = issue.get("body") or ""
        try:
            raw = _extract_state_json(body)
            # strict=False tolerates literal newlines in string values that
            # GitHub API responses embed when issue bodies have unescaped newlines.
            return FeatureState.model_validate(_json.loads(raw, strict=False))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_issue(self, feature_id: str) -> tuple[dict, int]:
        """Search for the parent issue and return (issue_dict, issue_number).

        Fetches all agentharness-feature issues and filters in-memory by
        feature_id parsed from the state JSON body.

        Raises ``KeyError`` if no issue is found.
        """
        items = await self._client.list_issues(labels=[self._feature_marker])
        for issue in items:
            candidate_id = _feature_id_from_issue(issue)
            if candidate_id is None:
                # list_issues may truncate long bodies — fetch the full issue
                full = await self._client.get_issue(issue["number"])
                candidate_id = _feature_id_from_issue(full)
                if candidate_id == feature_id:
                    return full, full["number"]
            elif candidate_id == feature_id:
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
        state = self._parse_state_from_issue(issue)
        if state is None:
            # Legacy: state stored in first comment
            comment = await self._get_state_comment(issue["number"])
            import json as _json
            json_str = _extract_state_json(comment["body"])
            state = FeatureState.model_validate(_json.loads(json_str, strict=False))

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
        await self._client.ensure_labels([self._feature_marker, status_label], color="0075ca")

        title = _feature_issue_title(state.feature_id)
        body = _replace_state_block(brief_content, state)
        issue = await self._client.create_issue(
            title=title,
            body=body,
            labels=[self._feature_marker, status_label],
        )
        issue_number: int = issue["number"]
        updated = state.model_copy(update={"state_issue_number": issue_number})
        await self._client.update_issue(issue_number, body=_replace_state_block(brief_content, updated))
        log.debug("Created state issue #%d for feature %s", issue_number, state.feature_id)

    async def get(self, feature_id: str, issue_number: int | None = None) -> FeatureState:
        """Fetch and reconstruct the FeatureState for the given feature_id.

        If *issue_number* is provided, the state issue is fetched directly
        (avoiding a full label search) and validated against *feature_id*.
        """
        if issue_number is not None:
            issue = await self._client.get_issue(issue_number)
            return await self._state_from_issue(issue)
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

    async def list_features(self) -> list[FeatureState]:
        """Return all known features as parsed FeatureState objects.

        Results are sorted by issue number descending (newest first). If the
        same feature_id appears in multiple issues, only the highest-numbered
        issue (most recent) is kept.
        """
        items = await self._client.list_issues(labels=[self._feature_marker], direction="desc")

        # feature_id -> (issue_number, issue_dict) — keep newest issue per feature
        seen: dict[str, tuple[int, dict]] = {}
        for issue in items:
            feature_id = _feature_id_from_issue(issue)
            if feature_id is None:
                log.warning(
                    "Issue #%d has %s label but no parseable state JSON — skipping",
                    issue["number"],
                    self._feature_marker,
                )
                continue
            issue_number: int = issue["number"]
            existing = seen.get(feature_id)
            if existing is None or issue_number > existing[0]:
                seen[feature_id] = (issue_number, issue)

        sorted_pairs = sorted(seen.values(), key=lambda pair: pair[0], reverse=True)

        states: list[FeatureState] = []
        for _issue_number, issue in sorted_pairs:
            try:
                state = await self._state_from_issue(issue)
                states.append(state)
            except Exception:
                log.warning(
                    "Could not parse state for issue #%d — skipping",
                    issue["number"],
                )
        return states

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.close()

    async def open_review(self, feature_id: str) -> str | None:
        """Open a GitHub pull request for the completed feature.

        Returns the PR URL on success, or None if the PR could not be created.
        The caller is responsible for ensuring the feature branch exists and
        all commits have been pushed before calling this method.
        """
        state = await self.get(feature_id)

        def _build_pr_body(s: FeatureState) -> str:
            phases_summary = "\n".join(
                f"- **{phase}**: {info.status.value}"
                for phase, info in s.phases.items()
            )
            tasks_summary = "\n".join(
                f"- {t.task_id}: {t.status.value}"
                for t in s.tasks
            )
            total = s.total_tokens_used()
            tokens_line = str(total.total) if total.total else "unknown"
            return (
                f"## Feature: {s.feature_id}\n\n"
                f"### Phases\n{phases_summary}\n\n"
                f"### Tasks\n{tasks_summary}\n\n"
                f"### Tokens used\n{tokens_line}\n\n"
                f"---\n*Generated by AgentHarness*\n"
            )

        try:
            default_branch = await self._client.get_default_branch()
            pr = await self._client.create_pull_request(
                title=f"{feature_id}: implementation complete",
                body=_build_pr_body(state),
                head=feature_id,
                base=default_branch,
                labels=[self._feature_marker],
            )
            pr_url = pr.get("html_url")
            if not pr_url:
                log.warning(
                    "PR #%s created but html_url missing in response for feature %s",
                    pr.get("number", "?"),
                    feature_id,
                )
                return None
            log.info("Opened PR #%s for feature %s: %s", pr.get("number", "?"), feature_id, pr_url)
            return pr_url
        except Exception as exc:
            log.error("Could not open PR for %s: %s", feature_id, exc)
            return None
