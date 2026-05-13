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
    EPIC_PAUSED,
    FEATURE_STATUS_TO_LABEL,
    FEAT_STATUS_LABELS,
    LABEL_TO_FEATURE_STATUS,
    TASK_STATE_LABELS,
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
# Slug helper — single source of truth shared between synthesis and matching.
#
# Algorithm contract (must match the /convertforagent skill byte-for-byte):
#   1. lowercase
#   2. replace runs of non-[a-z0-9] with a single "-"
#   3. strip leading/trailing "-"
#   4. truncate to 40 characters
#
# Any change here affects feature_id derivation across the entire pipeline.
# ---------------------------------------------------------------------------


def slug_title(title: str) -> str:
    """Return a 40-char URL-safe slug of *title* (matches /convertforagent)."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40]


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


def _parse_iso_timestamp(value: str | None) -> "datetime | None":
    """Parse a GitHub ISO-8601 timestamp into a UTC datetime, or None."""
    from datetime import datetime, timezone

    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _synthesize_raw_state(issue: dict) -> FeatureState:
    """Build a synthetic FeatureState for a labelled issue without a state block.

    Used by ``GitHubStateManager.list_features`` to surface raw issues in the TUI.
    The resulting state has ``is_raw is True`` (empty history) — that flag is the
    canonical signal that the issue still needs ``_convert_raw_issue`` before it
    can transition out of ``brainstormed``.
    """
    title = issue.get("title") or ""
    feature_id = f"feat-{slug_title(title)}"

    fields: dict = {
        "feature_id": feature_id,
        "status": FeatureStatus.brainstormed,
        "state_issue_number": int(issue["number"]),
        "branch_name": feature_id,
    }
    created_at = _parse_iso_timestamp(issue.get("created_at"))
    if created_at is not None:
        fields["created_at"] = created_at
    updated_at = _parse_iso_timestamp(issue.get("updated_at"))
    if updated_at is not None:
        fields["updated_at"] = updated_at

    return FeatureState(**fields)


# ---------------------------------------------------------------------------
# GitHubStateManager
# ---------------------------------------------------------------------------


def _tick_epic_pr_checkbox(body: str, issue_number: int) -> str:
    """Replace '- [ ] #N ...' with '- [x] #N ...' for the given issue number."""
    return re.sub(rf"- \[ \] #{issue_number}\b", f"- [x] #{issue_number}", body)


async def ensure_epic_branch(
    gh_client: "GitHubClient",
    epic_branch: str,
    default_sha: str,
) -> str:
    """Create *epic_branch* from *default_sha* if it doesn't exist.

    Returns the branch's current tip SHA. Idempotent: a 422 (Reference already
    exists) is silently tolerated and the existing SHA is returned instead.
    """
    from agentharness.github_client import GitHubApiError

    try:
        await gh_client.create_ref(f"refs/heads/{epic_branch}", default_sha)
        log.info("Created epic branch %s", epic_branch)
        return default_sha
    except GitHubApiError as exc:
        if exc.status_code == 422:
            log.info("Epic branch %s already exists — reusing", epic_branch)
            ref = await gh_client.get_ref(f"heads/{epic_branch}")
            return ref["object"]["sha"]
        raise


async def ensure_child_branch(
    gh_client: "GitHubClient",
    child_branch: str,
    epic_branch: str,
    epic_sha: str,
) -> None:
    """Create *child_branch* off *epic_sha* if it doesn't exist.

    Idempotent: 422 is tolerated (branch already present for a re-run).
    *epic_branch* is used only for log messages.
    """
    from agentharness.github_client import GitHubApiError

    try:
        await gh_client.create_ref(f"refs/heads/{child_branch}", epic_sha)
        log.info("Created child branch %s off %s", child_branch, epic_branch)
    except GitHubApiError as exc:
        if exc.status_code == 422:
            log.info("Child branch %s already exists — reusing", child_branch)
        else:
            raise


async def ensure_epic_pr(
    gh_client: "GitHubClient",
    epic_branch: str,
    parent_issue: dict,
    sub_issues: list[dict],
) -> dict:
    """Open a draft umbrella PR (*epic_branch* → default) if one doesn't exist.

    Returns the existing open PR dict if found, otherwise the newly created one.
    Idempotent: checks for an existing open PR before creating.
    """
    prs = await gh_client.list_pull_requests(head=epic_branch, state="open")
    if prs:
        log.debug("Umbrella PR for %s already exists (#%s)", epic_branch, prs[0].get("number"))
        return prs[0]

    parent_number = parent_issue["number"]
    pr_title = parent_issue.get("title") or epic_branch
    checklist = "\n".join(
        f"- [ ] #{si['number']} {si.get('title', '')}" for si in sub_issues
    )
    pr_body = (
        f"## Epic\n\nPart of #{parent_number}\n\n### Tasks\n\n{checklist}"
    )
    default_branch = await gh_client.get_default_branch()
    pr = await gh_client.create_pull_request(
        title=pr_title,
        body=pr_body,
        head=epic_branch,
        base=default_branch,
        draft=True,
    )
    log.info("Opened draft umbrella PR #%s for epic branch %s", pr.get("number"), epic_branch)
    return pr


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

    async def patch_existing_issue(
        self,
        issue_number: int,
        state: FeatureState,
        brief_content: str = "",
    ) -> None:
        """Embed harness state into an *existing* GitHub issue (no issue creation).

        Side effects:
          1. Ensure ``feature_marker`` and ``feat:brainstormed`` labels exist in
             the repo (idempotent).
          2. Add ``feat:brainstormed`` to the target issue. The original
             ``feature_marker`` label is left untouched.
          3. PATCH the issue body to carry an ``agentharness-state`` block —
             appending if absent, replacing if present.

        Idempotent: re-calling with the same *state* yields a byte-identical body.
        """
        from agentharness.github_labels import FEAT_BRAINSTORMED

        await self._client.ensure_labels(
            [self._feature_marker, FEAT_BRAINSTORMED],
            color="0075ca",
        )
        await self._client.add_labels(issue_number, [FEAT_BRAINSTORMED])

        issue = await self._client.get_issue(issue_number)
        existing_body = issue.get("body") or ""

        # If the brief is provided and is not already in the body, prepend it.
        if brief_content and brief_content not in existing_body:
            base_body = (
                f"{existing_body}\n\n{brief_content}".strip()
                if existing_body.strip()
                else brief_content
            )
        else:
            base_body = existing_body

        new_body = _replace_state_block(base_body, state)
        await self._client.update_issue(issue_number, body=new_body)

        log.info(
            "Patched existing issue #%d with state for feature %s",
            issue_number,
            state.feature_id,
        )

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

        Issues that carry the ``feature_marker`` label but do not embed an
        ``agentharness-state`` JSON block are surfaced as *synthetic* raw states
        (``status=brainstormed``, ``history=[]``). They are not persisted in
        synthetic form — the next ``patch_existing_issue`` call writes the real
        state block. ``state.is_raw`` distinguishes raw from initialised states.

        Results are sorted by issue number ascending (oldest/lowest ID first). When the
        same ``feature_id`` appears in multiple issues, only the highest-numbered
        issue is kept (raw + initialised dedup using the same rule).
        """
        items = await self._client.list_issues(labels=[self._feature_marker], direction="asc")

        # feature_id -> (issue_number, issue_dict, parsed_state_or_None) — prefer initialized, else newest
        seen: dict[str, tuple[int, dict, FeatureState | None]] = {}
        for issue in items:
            # Guard: skip stale queue issues that still carry feature_marker (e.g. from before
            # the agent-subtask migration). Task issues always have a task-state label.
            if {lbl["name"] for lbl in issue.get("labels", [])} & TASK_STATE_LABELS:
                continue
            parsed = self._parse_state_from_issue(issue)
            if parsed is not None:
                feature_id = parsed.feature_id
            else:
                title = issue.get("title") or ""
                feature_id = f"feat-{slug_title(title)}"
            existing = seen.get(feature_id)
            if existing is None:
                seen[feature_id] = (issue["number"], issue, parsed)
            elif parsed is not None and existing[2] is None:
                # Prefer initialized over raw regardless of issue number
                seen[feature_id] = (issue["number"], issue, parsed)
            elif (parsed is None) == (existing[2] is None) and issue["number"] > existing[0]:
                # Same type: take the newer one
                seen[feature_id] = (issue["number"], issue, parsed)

        sorted_triples = sorted(seen.values(), key=lambda t: t[0])

        states: list[FeatureState] = []
        for _issue_number, issue, parsed in sorted_triples:
            if parsed is None:
                states.append(_synthesize_raw_state(issue))
                continue
            try:
                state = await self._state_from_issue(issue)
                states.append(state)
            except Exception:
                log.debug(
                    "Could not reconstruct state for issue #%d — synthesising as raw",
                    issue["number"],
                )
                states.append(_synthesize_raw_state(issue))
        return states

    async def handle_epic_child_done(self, state: FeatureState) -> None:
        """Open/update/mark-ready the shared epic PR when an epic child completes."""
        if state.epic_parent is None or state.epic_branch is None:
            return

        # Find existing epic PR by branch
        prs = await self._client.list_pull_requests(head=state.epic_branch)
        open_pr = next((pr for pr in prs if pr.get("state") == "open"), None)

        if open_pr is None:
            # First child: open draft PR
            parent = await self._client.get_issue(state.epic_parent)
            sub_issues = await self._client.list_sub_issues(state.epic_parent)

            # Build PR title from parent epic title
            pr_title = parent.get("title") or state.epic_branch or state.feature_id

            # Build body: checklist of all child issues
            checklist_items = "\n".join(
                f"- [ ] #{si['number']} {si.get('title', '')}" for si in sub_issues
            )
            pr_body = f"## Epic\n\nPart of #{state.epic_parent}\n\n### Tasks\n\n{checklist_items}"

            default_branch = await self._client.get_default_branch()
            pr = await self._client.create_pull_request(
                title=pr_title,
                body=pr_body,
                head=state.epic_branch,
                base=default_branch,
                draft=True,
            )
            log.info("Opened draft epic PR #%s for %s", pr.get("number"), state.feature_id)
            open_pr = pr
            # Tick the first child's own checkbox
            if state.state_issue_number is not None:
                updated_body = _tick_epic_pr_checkbox(open_pr.get("body") or "", state.state_issue_number)
                if updated_body != (open_pr.get("body") or ""):
                    await self._client.update_pull_request(open_pr["number"], body=updated_body)
        else:
            # Subsequent children: tick the checkbox for this child's issue number
            child_issue_number = state.state_issue_number
            if child_issue_number is not None:
                current_body = open_pr.get("body") or ""
                updated_body = _tick_epic_pr_checkbox(current_body, child_issue_number)
                if updated_body != current_body:
                    await self._client.update_pull_request(open_pr["number"], body=updated_body)

        # If this is the last child, mark the PR ready for review
        if (
            state.epic_total is not None
            and state.epic_position is not None
            and state.epic_position >= state.epic_total
        ):
            await self._client.mark_pr_ready(open_pr["number"])
            log.info("Marked epic PR #%s ready", open_pr["number"])

    async def handle_epic_child_failed(
        self, state: FeatureState, reason: str = "unknown"
    ) -> None:
        """Apply EPIC_PAUSED label to parent epic + post comment on failing child."""
        if state.epic_parent is None:
            return

        try:
            await self._client.add_labels(state.epic_parent, [EPIC_PAUSED])
            log.info("Applied %s to epic issue #%s", EPIC_PAUSED, state.epic_parent)
        except Exception as exc:
            log.error("Failed to apply %s to epic #%s: %s", EPIC_PAUSED, state.epic_parent, exc)

        if state.state_issue_number is not None:
            comment = (
                f"⚠️ **Epic paused**: this feature failed.\n\n"
                f"**Reason**: {reason}\n\n"
                f"To retry: edit this issue's brief to clarify, then remove the "
                f"`epic:paused` label from the parent epic issue #{state.epic_parent}, "
                f"and re-run:\n```\nagentharness implement {state.feature_id}\n```"
            )
            try:
                await self._client.create_comment(state.state_issue_number, comment)
            except Exception as exc:
                log.error("Failed to post failure comment on #%s: %s", state.state_issue_number, exc)

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.close()

    async def open_review(
        self,
        feature_id: str,
        *,
        pr_title: str | None = None,
        pr_summary: str | None = None,
    ) -> str | None:
        """Open a GitHub pull request for the completed feature.

        When *pr_title* is provided and non-empty, it is used as the PR title;
        otherwise the default ``{feature_id}: implementation complete`` is used.

        When *pr_summary* is provided and non-empty, it forms the PR body
        followed by a separator, ``Closes #N`` (when an issue number exists),
        and the tokens footer. Otherwise the existing log-style body is used.

        Returns the PR URL on success, or None if the PR could not be created.
        """
        state = await self.get(feature_id)

        title = pr_title if pr_title else f"{feature_id}: implementation complete"
        body = self._compose_pr_body(state, pr_summary)

        try:
            head = state.branch_name or feature_id
            if state.epic_branch is not None:
                base = state.epic_branch
            else:
                base = await self._client.get_default_branch()

            pr = await self._client.create_pull_request(
                title=title,
                body=body,
                head=head,
                base=base,
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

    @staticmethod
    def _build_log_body(state: FeatureState) -> str:
        """Render the existing operational log-style PR body."""
        phases_summary = "\n".join(
            f"- **{phase}**: {info.status.value}"
            for phase, info in state.phases.items()
        )
        tasks_summary = "\n".join(
            f"- {t.task_id}: {t.status.value}"
            for t in state.tasks
        )
        total = state.total_tokens_used()
        tokens_line = str(total.total) if total.total else "unknown"
        closes = f"\nCloses #{state.state_issue_number}\n" if state.state_issue_number else ""
        return (
            f"## Feature: {state.feature_id}\n\n"
            f"### Phases\n{phases_summary}\n\n"
            f"### Tasks\n{tasks_summary}\n\n"
            f"### Tokens used\n{tokens_line}\n\n"
            f"---\n*Generated by AgentHarness*\n"
            f"{closes}"
        )

    @classmethod
    def _compose_pr_body(cls, state: FeatureState, pr_summary: str | None) -> str:
        """Pick between developer-authored body and the log-style body."""
        if not pr_summary or not pr_summary.strip():
            return cls._build_log_body(state)

        total = state.total_tokens_used()
        tokens_line = str(total.total) if total.total else "unknown"
        closes_block = (
            f"Closes #{state.state_issue_number}\n\n"
            if state.state_issue_number
            else ""
        )
        return (
            f"{pr_summary.rstrip()}\n\n"
            f"---\n\n"
            f"{closes_block}"
            f"### Tokens used\n{tokens_line}\n"
        )
