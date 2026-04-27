"""Interactive brainstorm session — the human-in-the-loop entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

from agentharness.config import Config
from agentharness.models import FeatureState, FeatureStatus, PipelineConfig
from agentharness.prompt_builder import load_agent_definition
from agentharness.state_manager import StateManager
from agentharness.storage import ArtifactStore, PipelineQueue, artifact_path

_BRAINSTORM_AGENT = Path(".agents/brainstorm.md")
_BRIEF_FILENAME = "brief.md"


def _slug_from_brief(brief_content: str) -> str:
    import re
    for line in brief_content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = re.sub(r"^#\s*(Feature Brief:\s*)?", "", line, flags=re.IGNORECASE)
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            return slug[:40]
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
    """Upload brief.md to blob storage and create initial state.json.

    Does NOT enqueue any pipeline tasks — call enqueue_planner() separately.
    """
    if config.storage_backend == "github":
        await _upload_brief_github(feature_id, brief_content, config)
        return

    from azure.storage.blob.aio import BlobServiceClient

    conn_str = config.storage.connection_string
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    store = ArtifactStore(blob_service, config.storage.container)
    state_mgr = StateManager(blob_service, config.storage.container)

    try:
        await store.ensure_container_exists()

        brief_blob = artifact_path(feature_id, "brief.md")
        await store.upload(brief_blob, brief_content)

        initial_state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.brainstorming,
            config=PipelineConfig(max_revisions=config.defaults.max_revisions),
        ).with_event("brief_uploaded")
        await state_mgr.create(initial_state)
    finally:
        await store.close()
        await blob_service.close()


async def _upload_brief_github(feature_id: str, brief_content: str, config: Config) -> None:
    """GitHub-backend implementation of upload_brief."""
    import base64
    from datetime import UTC, datetime

    from agentharness.github_client import GitHubClient
    from agentharness.github_state import GitHubStateManager

    client = GitHubClient.from_config(config)
    try:
        # 1. Create feature branch from the repo's default branch
        default_branch = await client.get_default_branch()
        main_sha = (await client.get_ref(f"heads/{default_branch}"))["object"]["sha"]
        await client.create_ref(f"refs/heads/{feature_id}", main_sha)

        # 2. Commit brief.md to the feature branch
        brief_path = f"artifacts/{feature_id}/brief.md"
        await client.put_content(
            path=brief_path,
            message=f"feat: add brief for {feature_id}",
            content=base64.b64encode(brief_content.encode()).decode(),
            sha=None,
            branch=feature_id,
        )

        # 3. Create initial FeatureState and persist as parent issue
        now = datetime.now(UTC)
        state = FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.analyzing,
            created_at=now,
            updated_at=now,
            config=PipelineConfig(
                max_revisions=config.defaults.max_revisions,
            ),
        )
        mgr = GitHubStateManager(client)
        await mgr.create(state, brief_content)
    finally:
        await client.close()


async def enqueue_planner(feature_id: str, config: Config) -> None:
    """Enqueue the analyst task, transitioning feature to 'analyzing' status."""
    if config.storage_backend == "github":
        await _enqueue_planner_github(feature_id, config)
        return

    from azure.storage.blob.aio import BlobServiceClient
    from agentharness.models import TaskMessage
    from agentharness.storage import phase_artifact_path

    conn_str = config.storage.connection_string
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    state_mgr = StateManager(blob_service, config.storage.container)

    try:
        brief_blob = artifact_path(feature_id, "brief.md")

        task = TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-analyzing-1",
            input_artifacts=[brief_blob],
            output_artifact=phase_artifact_path(feature_id, "spec", 1),
            agent_role="analyst",
        )

        analyst_queue = PipelineQueue.from_connection_string(conn_str, "analyst-queue")
        await analyst_queue.ensure_exists()
        await analyst_queue.send_task(task)
        await analyst_queue.close()

        await state_mgr.update(
            feature_id,
            lambda s: s.with_status(FeatureStatus.analyzing).with_event("pipeline_started"),
        )
    finally:
        await blob_service.close()


async def _enqueue_planner_github(feature_id: str, config: Config) -> None:
    """GitHub-backend implementation of enqueue_planner."""
    from agentharness.models import TaskMessage
    from agentharness.storage import artifact_path as _artifact_path
    from agentharness.storage import create_task_queue, phase_artifact_path

    queue = create_task_queue(config, "analyst-queue")
    try:
        task = TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-analyst",
            input_artifacts=[_artifact_path(feature_id, "brief.md")],
            output_artifact=phase_artifact_path(feature_id, "spec", 1),
            agent_role="analyst",
        )
        await queue.ensure_exists()
        await queue.send_task(task)
        log.info("Enqueued analyst task for %s", feature_id)
    finally:
        await queue.close()


async def upload_brief_file(brief_path: Path, config: Config) -> str:
    """Upload an existing local brief.md to blob storage. Returns feature_id."""
    if not brief_path.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")
    brief_content = brief_path.read_text(encoding="utf-8")
    feature_id = generate_feature_id(brief_content)
    await upload_brief(feature_id, brief_content, config)
    return feature_id
