"""Subprocess wrapper for Claude CLI invocation."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import tempfile
from pathlib import Path

from agentharness.models import AgentDefinition

log = logging.getLogger(__name__)


class AgentExecutionError(Exception):
    """Raised when the Claude CLI subprocess fails."""


async def run_agent(
    agent_def: AgentDefinition,
    prompt: str,
    work_dir: Path | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Run claude CLI non-interactively and return stdout.

    For agents with allowed_tools, passes --allowedTools flag.
    For agents without tools, runs in simple -p mode.
    """
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix=f"agent-{agent_def.id}-"))

    cmd = _build_command(agent_def, prompt)
    effective_timeout = timeout_seconds or agent_def.visibility_timeout
    log.info("Agent %r starting (timeout %ss, tools: %s)", agent_def.id, effective_timeout, agent_def.allowed_tools or "none")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(work_dir),
            env={**os.environ},
        )

        lines: list[str] = []
        stderr_chunks: list[bytes] = []

        async def _stream_stdout() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip("\n")
                lines.append(line)
                log.info("[claude] %s", line)

        async def _drain_stderr() -> None:
            assert proc.stderr
            data = await proc.stderr.read()
            stderr_chunks.append(data)

        await asyncio.wait_for(
            asyncio.gather(_stream_stdout(), _drain_stderr()),
            timeout=effective_timeout,
        )
        await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise AgentExecutionError(
            f"Agent {agent_def.id!r} timed out after {effective_timeout}s"
        )

    if proc.returncode != 0:
        err = b"".join(stderr_chunks).decode(errors="replace")
        raise AgentExecutionError(
            f"Agent {agent_def.id!r} exited with code {proc.returncode}: {err[:500]}"
        )

    output = "\n".join(lines)
    log.info("Agent %r done (%d chars output)", agent_def.id, len(output))
    return output


def _build_command(agent_def: AgentDefinition, prompt: str) -> list[str]:
    cmd = [
        "claude",
        "-p", prompt,
        "--model", agent_def.model,
    ]

    if agent_def.allowed_tools:
        cmd.extend(["--allowedTools", ",".join(agent_def.allowed_tools)])

    if agent_def.max_turns > 1:
        cmd.extend(["--max-turns", str(agent_def.max_turns)])

    if agent_def.output_format == "json":
        cmd.extend(["--output-format", "json"])

    return cmd
