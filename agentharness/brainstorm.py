"""Interactive brainstorm session — the human-in-the-loop entry point."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_BRAINSTORM_AGENT = Path(".agents/brainstorm.md")


def run_brainstorm_session(work_dir: Path, agent_path: Path) -> None:
    """Launch claude interactively with the brainstorm agent prompt.

    Uses os.execvp so the claude process inherits the terminal directly,
    giving it full TTY access for interactive use.
    """
    from agentharness.context_files import format_context_section, resolve_context_files
    from agentharness.prompt_builder import load_agent_definition

    agent_def = load_agent_definition(agent_path)
    project_root = agent_path.parent.parent

    system_prompt = agent_def.system_prompt
    if agent_def.context_files:
        resolved = resolve_context_files(agent_def.context_files, project_root)
        if resolved:
            system_prompt = format_context_section(resolved) + "\n\n" + system_prompt

    cmd = ["claude", "--system-prompt", system_prompt, "--model", agent_def.model]
    if agent_def.max_turns:
        cmd += ["--max-turns", str(agent_def.max_turns)]

    os.execvp("claude", cmd)


def start_brainstorm(config=None) -> None:
    """Start an interactive brainstorm session."""
    agent_path = _BRAINSTORM_AGENT
    if not agent_path.exists():
        raise FileNotFoundError(
            f"Brainstorm agent not found at {agent_path}. "
            "Run 'agentharness init' first."
        )
    with tempfile.TemporaryDirectory() as tmpdir:
        run_brainstorm_session(Path(tmpdir), agent_path)
