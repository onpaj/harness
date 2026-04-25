"""Interactive brainstorm session — the human-in-the-loop entry point."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agentharness.config import Config
from agentharness.models import FeatureState, FeatureStatus, PipelineConfig
from agentharness.prompt_builder import load_agent_definition
from agentharness.state_manager import StateManager
from agentharness.storage import ArtifactStore, PipelineQueue, artifact_path

_BRAINSTORM_AGENT = Path(".agents/brainstorm.md")
_BRIEF_FILENAME = "brief.md"


def generate_feature_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    entropy = hashlib.sha1(os.urandom(8)).hexdigest()[:6]
    return f"feat-{timestamp}-{entropy}"


def run_brainstorm_session(work_dir: Path, agent_path: Path) -> None:
    """Launch claude interactively in work_dir with the brainstorm agent prompt.

    Uses os.execvp so the claude process inherits the terminal directly,
    giving it full TTY access for interactive use.
    """
    agent_def = load_agent_definition(agent_path)
    os.chdir(work_dir)
    os.execvp("claude", [
        "claude",
        "--model", agent_def.model,
        "--system-prompt", agent_def.system_prompt,
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

    feature_id = generate_feature_id()
    work_dir = Path(tempfile.mkdtemp(prefix=f"brainstorm-{feature_id}-"))

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


async def enqueue_planner(feature_id: str, config: Config) -> None:
    """Enqueue the first planner task, transitioning feature to 'planning' status."""
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
            task_id=f"{feature_id}-planning-1",
            input_artifacts=[brief_blob],
            output_artifact=phase_artifact_path(feature_id, "spec", 1),
            agent_role="planner",
        )

        planner_queue = PipelineQueue.from_connection_string(conn_str, "planner-queue")
        await planner_queue.ensure_exists()
        await planner_queue.send_task(task)
        await planner_queue.close()

        await state_mgr.update(
            feature_id,
            lambda s: s.with_status(FeatureStatus.planning).with_event("pipeline_started"),
        )
    finally:
        await blob_service.close()


async def upload_brief_file(brief_path: Path, config: Config) -> str:
    """Upload an existing local brief.md to blob storage. Returns feature_id."""
    if not brief_path.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")
    brief_content = brief_path.read_text(encoding="utf-8")
    feature_id = generate_feature_id()
    await upload_brief(feature_id, brief_content, config)
    return feature_id
