"""Assemble Claude prompts from agent definitions and input artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from agentharness.context_files import ContextFileResult, format_context_section
from agentharness.models import AgentDefinition, TaskMessage

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)

_ESTIMATED_CHARS_PER_TOKEN = 4
_CONTEXT_WARNING_TOKENS = 150_000


def load_agent_definition(path: Path) -> AgentDefinition:
    """Parse a Markdown agent definition file with YAML frontmatter."""
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"Agent file {path} is missing YAML frontmatter (--- block)")
    frontmatter_str, body = match.groups()
    frontmatter = yaml.safe_load(frontmatter_str)
    return AgentDefinition(
        **frontmatter,
        system_prompt=body.strip(),
    )


def build_prompt(
    agent_def: AgentDefinition,
    task: TaskMessage,
    artifact_contents: dict[str, str],
    context_result: Optional[ContextFileResult] = None,
) -> str:
    """Assemble the full prompt string to pass to the Claude CLI."""
    sections: list[str] = [agent_def.system_prompt]

    context_section = format_context_section(context_result.files) if context_result else ""
    if context_section:
        sections.append(context_section)

    if artifact_contents:
        artifact_blocks = "\n\n".join(
            f"### {name}\n{content}" for name, content in artifact_contents.items()
        )
        sections.append(f"---\n## Input Artifacts\n\n{artifact_blocks}")

    if task.context:
        sections.append(f"---\n## Task\n\n{task.context}")

    if task.review_feedback:
        sections.append(
            f"---\n## Review Feedback\n\n"
            f"The following issues were found in the previous implementation. "
            f"Please address each one:\n\n{task.review_feedback}"
        )

    prompt = "\n\n".join(sections)
    _warn_if_large(prompt, task.task_id)
    return prompt


def _warn_if_large(prompt: str, task_id: str) -> None:
    estimated_tokens = len(prompt) // _ESTIMATED_CHARS_PER_TOKEN
    if estimated_tokens > _CONTEXT_WARNING_TOKENS:
        import logging
        logging.getLogger(__name__).warning(
            "Prompt for task %s is ~%d tokens, approaching context limit. "
            "Consider passing large artifacts as files instead of inline.",
            task_id,
            estimated_tokens,
        )


def artifact_label(blob_path: str) -> str:
    """Extract a human-readable name from a blob path for use in prompt sections."""
    return Path(blob_path).name
