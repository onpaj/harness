"""Unit tests for prompt_builder module."""

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agentharness.context_files import ContextFileResult, ResolvedContextFile
from agentharness.models import AgentDefinition
from agentharness.prompt_builder import build_prompt, artifact_label, load_agent_definition


@dataclass
class TaskMessage:
    """Minimal task data container for testing prompt_builder."""
    feature_id: str
    task_id: str
    output_artifact: str
    agent_role: str
    input_artifacts: list[Any] = field(default_factory=list)
    context: str | None = None
    review_feedback: str | None = None


def make_agent_def(**overrides) -> AgentDefinition:
    defaults = dict(
        id="test-agent",
        model="claude-sonnet-4-6",
        phase="testing",
        system_prompt="You are a test agent.",
    )
    return AgentDefinition(**{**defaults, **overrides})


def make_task(**overrides) -> TaskMessage:
    defaults = dict(
        feature_id="feat-test",
        task_id="feat-test-1",
        input_artifacts=[],
        output_artifact="artifacts/feat-test/out.md",
        agent_role="test-agent",
    )
    return TaskMessage(**{**defaults, **overrides})


class TestBuildPrompt:
    def test_includes_system_prompt(self):
        agent = make_agent_def(system_prompt="Be helpful.")
        task = make_task()
        result = build_prompt(agent, task, {})
        assert "Be helpful." in result

    def test_includes_artifact_contents(self):
        agent = make_agent_def()
        task = make_task()
        result = build_prompt(agent, task, {"spec.md": "# My Spec\nContent here."})
        assert "## Input Artifacts" in result
        assert "### spec.md" in result
        assert "# My Spec" in result

    def test_includes_task_context(self):
        agent = make_agent_def()
        task = make_task(context="Implement the login form.")
        result = build_prompt(agent, task, {})
        assert "## Task" in result
        assert "Implement the login form." in result

    def test_includes_review_feedback(self):
        agent = make_agent_def()
        task = make_task(review_feedback="Missing input validation.")
        result = build_prompt(agent, task, {})
        assert "## Review Feedback" in result
        assert "Missing input validation." in result

    def test_no_artifact_section_when_empty(self):
        agent = make_agent_def()
        task = make_task()
        result = build_prompt(agent, task, {})
        assert "## Input Artifacts" not in result

    def test_no_context_section_when_none(self):
        agent = make_agent_def()
        task = make_task(context=None)
        result = build_prompt(agent, task, {})
        assert "## Task" not in result

    def test_no_feedback_section_when_none(self):
        agent = make_agent_def()
        task = make_task(review_feedback=None)
        result = build_prompt(agent, task, {})
        assert "## Review Feedback" not in result

    def test_multiple_artifacts_are_all_included(self):
        agent = make_agent_def()
        task = make_task()
        artifacts = {"spec.md": "spec content", "arch.md": "arch content"}
        result = build_prompt(agent, task, artifacts)
        assert "### spec.md" in result
        assert "### arch.md" in result
        assert "spec content" in result
        assert "arch content" in result


def make_resolved_file(display_path: str, content: str) -> ResolvedContextFile:
    return ResolvedContextFile(
        declared_path=display_path,
        resolved_path=Path(display_path),
        display_path=display_path,
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


def make_context_result(*files: ResolvedContextFile) -> ContextFileResult:
    return ContextFileResult(
        agent_name="test-agent",
        files=tuple(files),
        warnings=(),
        total_bytes=sum(f.size_bytes for f in files),
    )


class TestBuildPromptContextFiles:
    def test_none_context_result_matches_original_output(self):
        agent = make_agent_def(system_prompt="Be helpful.")
        task = make_task()
        without_context = build_prompt(agent, task, {})
        with_none = build_prompt(agent, task, {}, context_result=None)
        assert without_context == with_none

    def test_empty_context_result_matches_original_output(self):
        agent = make_agent_def(system_prompt="Be helpful.")
        task = make_task()
        without_context = build_prompt(agent, task, {})
        empty_result = make_context_result()
        with_empty = build_prompt(agent, task, {}, context_result=empty_result)
        assert without_context == with_empty

    def test_context_section_header_appears_with_files(self):
        agent = make_agent_def()
        task = make_task()
        result = make_context_result(make_resolved_file("/docs/style.md", "# Style Guide"))
        prompt = build_prompt(agent, task, {}, context_result=result)
        assert "## Agent Context Files" in prompt

    def test_context_file_block_format(self):
        agent = make_agent_def()
        task = make_task()
        result = make_context_result(make_resolved_file("/docs/style.md", "# Style Guide"))
        prompt = build_prompt(agent, task, {}, context_result=result)
        assert "### Context: /docs/style.md" in prompt
        assert "# Style Guide" in prompt

    def test_context_section_positioned_before_artifacts(self):
        agent = make_agent_def(system_prompt="Instructions here.")
        task = make_task()
        artifacts = {"spec.md": "spec content"}
        result = make_context_result(make_resolved_file("/docs/style.md", "style content"))
        prompt = build_prompt(agent, task, artifacts, context_result=result)
        ctx_pos = prompt.index("## Agent Context Files")
        artifacts_pos = prompt.index("## Input Artifacts")
        assert ctx_pos < artifacts_pos

    def test_context_section_positioned_after_instructions(self):
        agent = make_agent_def(system_prompt="Instructions here.")
        task = make_task()
        result = make_context_result(make_resolved_file("/docs/style.md", "style content"))
        prompt = build_prompt(agent, task, {}, context_result=result)
        instructions_pos = prompt.index("Instructions here.")
        ctx_pos = prompt.index("## Agent Context Files")
        assert instructions_pos < ctx_pos

    def test_multiple_files_all_appear_in_prompt(self):
        agent = make_agent_def()
        task = make_task()
        result = make_context_result(
            make_resolved_file("/docs/a.md", "content A"),
            make_resolved_file("/docs/b.md", "content B"),
        )
        prompt = build_prompt(agent, task, {}, context_result=result)
        assert "### Context: /docs/a.md" in prompt
        assert "content A" in prompt
        assert "### Context: /docs/b.md" in prompt
        assert "content B" in prompt

    def test_multiple_files_ordered_as_provided(self):
        agent = make_agent_def()
        task = make_task()
        result = make_context_result(
            make_resolved_file("/docs/a.md", "content A"),
            make_resolved_file("/docs/b.md", "content B"),
        )
        prompt = build_prompt(agent, task, {}, context_result=result)
        pos_a = prompt.index("### Context: /docs/a.md")
        pos_b = prompt.index("### Context: /docs/b.md")
        assert pos_a < pos_b

    def test_no_context_header_without_files(self):
        agent = make_agent_def()
        task = make_task()
        result = make_context_result()
        prompt = build_prompt(agent, task, {}, context_result=result)
        assert "## Agent Context Files" not in prompt

    def test_no_extra_blank_lines_when_context_is_none(self):
        agent = make_agent_def(system_prompt="Instructions.")
        task = make_task(context="Do the task.")
        without = build_prompt(agent, task, {})
        with_none = build_prompt(agent, task, {}, context_result=None)
        assert without == with_none
        assert "\n\n\n" not in with_none


class TestArtifactLabel:
    def test_extracts_filename_from_blob_path(self):
        assert artifact_label("artifacts/feat-42/spec.r1.md") == "spec.r1.md"

    def test_handles_nested_path(self):
        assert artifact_label("artifacts/feat-42/impl/auth.r1.md") == "auth.r1.md"


class TestLoadAgentDefinition:
    def test_parses_frontmatter_and_body(self, tmp_path):
        agent_file = tmp_path / "test.md"
        agent_file.write_text(textwrap.dedent("""\
            ---
            id: test
            model: claude-sonnet-4-6
            phase: testing
            max_turns: 5
            ---

            You are a test agent. Do test things.
        """))
        agent = load_agent_definition(agent_file)
        assert agent.id == "test"
        assert agent.model == "claude-sonnet-4-6"
        assert agent.max_turns == 5
        assert "You are a test agent." in agent.system_prompt

    def test_raises_on_missing_frontmatter(self, tmp_path):
        agent_file = tmp_path / "bad.md"
        agent_file.write_text("No frontmatter here.")
        with pytest.raises(ValueError, match="YAML frontmatter"):
            load_agent_definition(agent_file)
