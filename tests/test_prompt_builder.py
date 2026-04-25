"""Unit tests for prompt_builder module."""

import textwrap
from pathlib import Path

import pytest

from agentharness.models import AgentDefinition, TaskMessage
from agentharness.prompt_builder import build_prompt, artifact_label, load_agent_definition


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
