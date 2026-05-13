"""Interactive brainstorm session — the human-in-the-loop entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

from agentharness.config import Config
from agentharness.github_client import GitHubClient
from agentharness.models import FeatureState, FeatureStatus, PipelineConfig, TaskMessage
from agentharness.prompt_builder import load_agent_definition
from agentharness.storage import (
    artifact_path,
    create_artifact_store,
    create_state_manager,
    create_task_queue,
    phase_artifact_path,
)

_BRAINSTORM_AGENT = Path(".agents/brainstorm.md")
_BRIEF_FILENAME = "brief.md"


def _slug_from_brief(brief_content: str) -> str:
    """Extract the H1 line from *brief_content* and slug it via slug_title."""
    import re
    from agentharness.github_state import slug_title

    for line in brief_content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = re.sub(r"^#\s*(Feature Brief:\s*)?", "", line, flags=re.IGNORECASE)
            return slug_title(title)
    return "untitled"


def generate_feature_id(brief_content: str = "") -> str:
    slug = _slug_from_brief(brief_content) if brief_content else "untitled"
    return f"feat-{slug}"


def run_brainstorm_session(work_dir: Path, agent_path: Path) -> None:
    """Launch claude interactively in work_dir with the brainstorm agent prompt.

    Uses os.execvp so the claude process inherits the terminal directly,
    giving it full TTY access for interactive use.
    """
    from agentharness.context_files import format_context_section, resolve_context_files

    agent_def = load_agent_definition(agent_path)
    project_root = agent_path.parent.parent

    system_prompt = agent_def.system_prompt
    if agent_def.context_files:
        context_result = resolve_context_files(
            agent_def.context_files,
            agent_name=agent_def.id,
            config_dir=project_root,
        )
        context_section = format_context_section(context_result.files)
        if context_section:
            system_prompt = f"{system_prompt}\n\n{context_section}"

    os.chdir(work_dir)
    os.execvp("claude", [
        "claude",
        "--model", agent_def.model,
        "--system-prompt", system_prompt,
        "--allowedTools", "write",
        "--max-turns", str(agent_def.max_turns),
    ])
    # execvp replaces the current process — nothing after this runs


def start_brainstorm(config: Config | None = None) -> None:
    """Entry point for `agentharness brainstorm`.

    1. Runs interactive claude session in a temp directory
    2. After session ends, reads brief.md written by the agent
    3. Asks user to confirm submission
    4. Submits to pipeline
    """
    agent_path = _BRAINSTORM_AGENT
    if not agent_path.exists():
        print(f"Error: Agent definition not found at {agent_path}", file=sys.stderr)
        sys.exit(1)

    feature_id = generate_feature_id()  # placeholder until brief is written
    work_dir = Path(tempfile.mkdtemp(prefix=f"brainstorm-"))

    print(f"\n=== AgentHarness Brainstorm Session ===")
    print(f"Feature ID: {feature_id}")
    print(f"Working directory: {work_dir}")
    print(f"\nStarting brainstorm agent... (type your feature idea to begin)")
    print(f"The agent will ask clarifying questions and write brief.md when done.\n")

    # Fork: parent waits, child execs claude
    pid = os.fork()
    if pid == 0:
        # Child: replace with claude process
        run_brainstorm_session(work_dir, agent_path)
        sys.exit(0)  # unreachable, but satisfies linters

    # Parent: wait for claude to exit
    _, exit_status = os.waitpid(pid, 0)
    exit_code = os.waitstatus_to_exitcode(exit_status)

    if exit_code != 0:
        print(f"\nBrainstorm session exited with code {exit_code}.", file=sys.stderr)
        sys.exit(exit_code)

    # Read the brief
    brief_path = work_dir / _BRIEF_FILENAME
    if not brief_path.exists():
        print(
            f"\nNo {_BRIEF_FILENAME} found in {work_dir}. "
            "Did the agent finish? You can run again to retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    brief_content = brief_path.read_text(encoding="utf-8")
    feature_id = generate_feature_id(brief_content)
    print(f"\n{'='*60}")
    print("Generated Brief:")
    print("="*60)
    print(brief_content)
    print("="*60)

    answer = input("\nUpload brief to Azure? [y/N] ").strip().lower()
    if answer != "y":
        print(f"Not uploaded. Brief saved locally at: {brief_path}")
        return

    if config is None:
        from agentharness.config import load_config
        config = load_config()

    asyncio.run(upload_brief(feature_id, brief_content, config))
    print(f"\nBrief uploaded. Feature ID: {feature_id}")
    print(f"Start the pipeline when ready: agentharness implement {feature_id}")


async def upload_brief(feature_id: str, brief_content: str, config: Config) -> None:
    """Upload brief.md to storage and create initial state.

    Does NOT enqueue any pipeline tasks — call enqueue_planner() separately.
    """
    store = create_artifact_store(config, feature_id=feature_id)
    state_mgr = create_state_manager(config)

    try:
        brief_blob = artifact_path(feature_id, "brief.md")
        await store.upload(brief_blob, brief_content)

        branch_name = feature_id if config.storage_backend == "github" else None
        initial_state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.brainstormed,
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
                max_analyst_iterations=config.max_analyst_iterations,
            ),
            branch_name=branch_name,
        ).with_event("brief_uploaded")
        await state_mgr.create(initial_state, brief_content=brief_content)
        log.info("Uploaded brief for %s", feature_id)
    finally:
        await store.close()


async def enqueue_planner(feature_id: str, config: Config) -> None:
    """Enqueue the analyst task, transitioning feature to 'analyzing' status."""
    from datetime import UTC, datetime

    state_mgr = create_state_manager(config)
    try:
        if config.storage_backend == "github":
            try:
                await state_mgr.get(feature_id)
            except KeyError:
                await _convert_raw_issue(feature_id, config)

        state = await state_mgr.update(
            feature_id,
            lambda s: s.with_status(FeatureStatus.analyzing).with_event("pipeline_started"),
        )

        work_dir_str: str | None = None

        if config.storage_backend == "github":
            branch_name = state.branch_name or feature_id
            brief_content = await _fetch_brief_for_feature(state, config)

            store = create_artifact_store(config, feature_id=branch_name)
            try:
                # Ensure the clone exists and the feature branch is checked out.
                await store._ensure_clone()
                await store._checkout_or_create(branch_name)

                work_dir = store.get_work_dir()
                work_dir_str = str(work_dir)

                # Also commit brief.md to the branch so artifact downloads succeed.
                await store.upload(artifact_path(feature_id, "brief.md"), brief_content)
            finally:
                await store.close()

            # Persist branch_name and worktree_path so run_task can find the clone.
            state = await state_mgr.update(
                feature_id,
                lambda s: s.model_copy(update={
                    "branch_name": branch_name,
                    "worktree_path": work_dir_str,
                    "updated_at": datetime.now(UTC),
                }),
            )

        queue = create_task_queue(config, "analyst-queue")
        try:
            task = TaskMessage(
                feature_id=feature_id,
                task_id=f"{feature_id}-analyst",
                input_artifacts=[artifact_path(feature_id, "brief.md")],
                output_artifact=phase_artifact_path(feature_id, "spec", 1),
                agent_role="analyst",
                state_issue_number=state.state_issue_number,
                work_dir=work_dir_str,
            )
            await queue.ensure_exists()
            await queue.send_task(task)
            log.info("Enqueued analyst task for %s", feature_id)
        finally:
            await queue.close()
    finally:
        await state_mgr.close()


async def _fetch_brief_for_feature(state: FeatureState, config: Config) -> str:
    """Return the feature brief text from the GitHub state issue body."""
    if state.state_issue_number is None:
        log.warning("No state_issue_number on state; returning empty brief")
        return ""
    from agentharness.github_client import GitHubClient
    from agentharness.github_state import extract_brief_from_issue_body

    client = GitHubClient.from_config(config)
    try:
        issue = await client.get_issue(state.state_issue_number)
        body = issue.get("body") or ""
        return extract_brief_from_issue_body(body)
    finally:
        await client.close()


async def _convert_raw_issue(feature_id: str, config: Config) -> None:
    """Convert a labelled-but-not-initialised GitHub issue into a harness feature.

    Performs the in-Python equivalent of the ``/convertforagent`` skill:
      1. Find the open issue whose title slug matches *feature_id*.
      2. Create the feature branch (idempotent; existing branch is tolerated).
      3. Upload the issue body as ``artifacts/{feature_id}/brief.md``.
      4. Patch the issue with labels + state JSON block.

    Idempotent on retry: branch creation is 422-tolerant, artifact upload
    overwrites any existing ``brief.md``, and ``patch_existing_issue`` replaces
    the state block in place. Raises ``ValueError`` if no open issue matches.
    """
    from agentharness.github_client import GitHubApiError
    from agentharness.github_state import slug_title

    expected_slug = feature_id.removeprefix("feat-")

    gh_client = GitHubClient.from_config(config)
    state_mgr = create_state_manager(config)
    store = None
    try:
        # 1. Find the matching issue
        issues = await gh_client.list_issues(labels=[config.github.feature_marker])
        match: dict | None = None
        for issue in issues:
            title = issue.get("title") or ""
            if slug_title(title) == expected_slug:
                match = issue
                break
        if match is None:
            raise ValueError(
                f"no raw issue found for {feature_id!r} "
                f"(no open issue with label {config.github.feature_marker!r} "
                f"slugs to {expected_slug!r})"
            )
        issue_number = int(match["number"])
        brief_content = match.get("body") or ""

        # 2. Detect epic parent (sub-issue relationship)
        parent_issue = await gh_client.get_parent_issue(issue_number)
        epic_parent: int | None = None
        epic_position: int | None = None
        epic_branch: str | None = None
        branch_name = feature_id  # each child keeps its own branch name (not shared)
        sub_issues: list[dict] = []

        if parent_issue is not None:
            parent_number = int(parent_issue["number"])
            epic_branch = "epic-" + slug_title(parent_issue.get("title") or "")
            epic_parent = parent_number

            sub_issues = await gh_client.list_sub_issues(parent_number)
            if not sub_issues:
                log.warning(
                    "list_sub_issues returned empty for parent #%d — ignoring epic relationship",
                    parent_number,
                )
                epic_parent = None
                epic_branch = None
            else:
                sub_numbers = [int(s["number"]) for s in sub_issues]
                try:
                    epic_position = sub_numbers.index(issue_number) + 1
                except ValueError:
                    epic_position = len(sub_numbers) + 1

        # 3. Create store with the child's own branch (branch_name = feature_id)
        store = create_artifact_store(config, feature_id=branch_name)

        # 4. Create branches idempotently
        default_branch = await gh_client.get_default_branch()
        ref = await gh_client.get_ref(f"heads/{default_branch}")
        default_sha = ref["object"]["sha"]

        if epic_parent is not None and epic_branch is not None:
            from agentharness.github_state import (
                ensure_child_branch,
                ensure_epic_branch,
                ensure_epic_pr,
            )
            epic_sha = await ensure_epic_branch(gh_client, epic_branch, default_sha)
            await ensure_child_branch(gh_client, branch_name, epic_branch, epic_sha)
            await ensure_epic_pr(gh_client, epic_branch, parent_issue, sub_issues)
        else:
            try:
                await gh_client.create_ref(f"refs/heads/{branch_name}", default_sha)
                log.info("Created branch %s", branch_name)
            except GitHubApiError as exc:
                if exc.status_code == 422:
                    log.info("Branch %s already exists — skipping creation", branch_name)
                else:
                    raise

        # 5. Upload brief
        await store.upload(artifact_path(feature_id, "brief.md"), brief_content)

        # 6. Build state and patch the issue
        epic_total: int | None = len(sub_issues) if sub_issues else None
        state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.brainstormed,
            state_issue_number=issue_number,
            branch_name=branch_name,
            epic_parent=epic_parent,
            epic_position=epic_position,
            epic_branch=epic_branch,
            epic_total=epic_total,
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
                max_analyst_iterations=config.max_analyst_iterations,
            ),
        ).with_event("brief_uploaded")
        await state_mgr.patch_existing_issue(issue_number, state, brief_content=brief_content)
        log.info("Auto-converted raw issue #%d → feature %s", issue_number, feature_id)
    finally:
        await gh_client.close()
        if store is not None:
            await store.close()
        await state_mgr.close()


async def upload_brief_file(brief_path: Path, config: Config) -> str:
    """Upload an existing local brief.md to blob storage. Returns feature_id."""
    if not brief_path.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")
    brief_content = brief_path.read_text(encoding="utf-8")
    feature_id = generate_feature_id(brief_content)
    await upload_brief(feature_id, brief_content, config)
    return feature_id
