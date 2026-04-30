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
                    readable = _format_stream_line(line)
                    if readable:
                        log.info("%s", readable)
                        if log_fh:
                            log_fh.write(readable + "\n")
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


def _format_stream_line(line: str) -> str | None:
    """Convert a stream-json event line into a human-readable log string.

    Returns None for events that add no value (init, system, empty).
    """
    if not line.strip():
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line  # pass through non-JSON lines as-is

    event_type = event.get("type", "")

    if event_type == "assistant":
        message = event.get("message") or {}
        parts: list[str] = []
        for block in message.get("content", []):
            btype = block.get("type", "")
            if btype == "text":
                text = block.get("text", "").strip()
                if text:
                    parts.append(text)
            elif btype == "tool_use":
                tool_name = block.get("name", "?")
                inp = block.get("input") or {}
                if "command" in inp:
                    parts.append(f"[tool:{tool_name}] {inp['command']}")
                elif "path" in inp:
                    parts.append(f"[tool:{tool_name}] {inp['path']}")
                else:
                    parts.append(f"[tool:{tool_name}]")
        return "\n".join(parts) if parts else None

    if event_type == "tool_result":
        content = event.get("content") or []
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        combined = " ".join(t.strip() for t in texts if t.strip())
        if combined:
            max_len = 300
            snippet = combined[:max_len] + ("…" if len(combined) > max_len else "")
            return f"[tool_result] {snippet}"
        return None

    if event_type == "result":
        subtype = event.get("subtype", "")
        tokens_in = event.get("total_input_tokens", 0)
        tokens_out = event.get("total_output_tokens", 0)
        return f"[result:{subtype}] in={tokens_in} out={tokens_out}"

    return None


def _build_command(agent_def: AgentDefinition, prompt: str) -> list[str]:
    cmd = [
        "claude",
        "-p", prompt,
        "--verbose",
        "--model", agent_def.model,
        "--output-format", "stream-json",
    ]

    if agent_def.allowed_tools:
        cmd.extend(["--allowedTools", ",".join(agent_def.allowed_tools)])

    if agent_def.max_turns > 1:
        cmd.extend(["--max-turns", str(agent_def.max_turns)])

    return cmd


def _parse_json_output(raw: str, agent_id: str) -> tuple[str, TokenUsage | None]:
    """Parse claude --output-format stream-json stdout.

    Walks every NDJSON line, summing `assistant.message.usage` across parent and
    sidechain (Task subagent) turns. Final text is taken from the `result` event;
    on truncation, falls back to the last `assistant` event's text content.

    Returns:
        (text, usage):
            text  — final result text, or best-effort assistant content if truncated.
            usage — aggregated TokenUsage across parent + all sidechain assistant
                    events, or None if no parseable JSON lines or zero total.
    """
    if not raw.strip():
        return "", None

    assistant_tokens = TokenUsage()
    result_text: str | None = None
    result_total_input: int | None = None
    result_total_output: int | None = None
    last_assistant_text = ""
    any_json = False
    assistant_turns = 0

    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.debug("Agent %r: skipping malformed stream line", agent_id)
            continue
        any_json = True

        event_type = event.get("type")
        if event_type == "assistant":
            assistant_turns += 1
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            assistant_tokens = assistant_tokens + TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            )
            content = message.get("content") or []
            texts = [
                b.get("text", "")
                for b in content
                if b.get("type") == "text" and b.get("text")
            ]
            if texts:
                last_assistant_text = texts[-1]

        elif event_type == "result":
            result_text = str(event.get("result", ""))
            total_in = event.get("total_input_tokens")
            total_out = event.get("total_output_tokens")
            if total_in is not None:
                result_total_input = int(total_in)
            if total_out is not None:
                result_total_output = int(total_out)

    if not any_json:
        log.warning("Agent %r: output is not JSON, treating as plain text", agent_id)
        return raw, None

    tokens = TokenUsage(
        input_tokens=result_total_input if result_total_input is not None else assistant_tokens.input_tokens,
        output_tokens=result_total_output if result_total_output is not None else assistant_tokens.output_tokens,
        cache_creation_tokens=assistant_tokens.cache_creation_tokens,
        cache_read_tokens=assistant_tokens.cache_read_tokens,
    )

    text = result_text if result_text is not None else last_assistant_text
    log.debug(
        "Agent %r: parsed %d assistant turns, tokens=in=%d out=%d cache_c=%d cache_r=%d",
        agent_id,
        assistant_turns,
        tokens.input_tokens,
        tokens.output_tokens,
        tokens.cache_creation_tokens,
        tokens.cache_read_tokens,
    )

    if tokens.total == 0:
        return text, None
    return text, tokens
