"""Subprocess wrapper for Claude CLI invocation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agentharness.models import AgentDefinition, TokenUsage

log = logging.getLogger(__name__)


class AgentExecutionError(Exception):
    """Raised when the Claude CLI subprocess fails."""


@dataclass
class RunResult:
    output: str
    tokens: TokenUsage | None


async def run_agent(
    agent_def: AgentDefinition,
    prompt: str,
    work_dir: Path | None = None,
    timeout_seconds: float | None = None,
    log_file: Path | None = None,
    worktree_path: str | None = None,
) -> RunResult:
    """Run claude CLI non-interactively and return output with token usage.

    Always uses --output-format json internally to capture token usage.
    For agents with allowed_tools, passes --allowedTools flag.
    When worktree_path is set it overrides the subprocess cwd.
    """
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix=f"agent-{agent_def.id}-"))

    subprocess_cwd = worktree_path if worktree_path is not None else str(work_dir)

    cmd = _build_command(agent_def, prompt)
    effective_timeout = timeout_seconds or agent_def.visibility_timeout
    log.info("Agent %r starting (timeout %ss, tools: %s)", agent_def.id, effective_timeout, agent_def.allowed_tools or "none")

    try:
        _64MB = 64 * 1024 * 1024
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=subprocess_cwd,
            env={**os.environ},
            limit=_64MB,
        )

        lines: list[str] = []
        stderr_chunks: list[bytes] = []

        async def _stream_stdout() -> None:
            assert proc.stdout
            log_fh = open(log_file, "a") if log_file else None
            try:
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").rstrip("\n")
                    lines.append(line)
                    log.info("[claude] %s", line)
                    if log_fh:
                        log_fh.write(line + "\n")
                        log_fh.flush()
            finally:
                if log_fh:
                    log_fh.close()

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

    raw_output = "\n".join(lines)
    text, tokens = _parse_json_output(raw_output, agent_def.id)
    if tokens:
        log.info(
            "Agent %r done (%d chars, in=%d out=%d cache_read=%d)",
            agent_def.id, len(text), tokens.input_tokens, tokens.output_tokens, tokens.cache_read_tokens,
        )
    else:
        log.info("Agent %r done (%d chars output)", agent_def.id, len(text))
    return RunResult(output=text, tokens=tokens)


def _build_command(agent_def: AgentDefinition, prompt: str) -> list[str]:
    cmd = [
        "claude",
        "-p", prompt,
        "--model", agent_def.model,
        "--output-format", "json",
    ]

    if agent_def.allowed_tools is not None:
        if agent_def.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(agent_def.allowed_tools)])
        else:
            cmd.extend(["--tools", ""])

    if agent_def.max_turns > 1:
        cmd.extend(["--max-turns", str(agent_def.max_turns)])

    return cmd


def _parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]:
    """Parse claude --output-format json stdout. Returns (text_content, token_usage)."""
    text = raw.strip()
    if not text:
        return "", None

    data: dict | None = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass

    if data is None:
        log.warning("Agent %r: output is not JSON, treating as plain text", agent_id)
        return raw, None

    result_text = data.get("result", raw)

    usage = data.get("usage") or {}
    tokens = TokenUsage(
        input_tokens=data.get("total_input_tokens", usage.get("input_tokens", 0)),
        output_tokens=data.get("total_output_tokens", usage.get("output_tokens", 0)),
        cache_creation_tokens=data.get("total_cache_creation_input_tokens", usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=data.get("total_cache_read_input_tokens", usage.get("cache_read_input_tokens", 0)),
    )

    if tokens.total == 0:
        return result_text, None

    return result_text, tokens
