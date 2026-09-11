"""Guards for the agent definitions shipped by `agentharness init`.

`agentharness/data/agents/` and `agentharness/data/claude-agents/` are
single-tree — unlike `.claude/skills`, they have no mirrored copy in this
repo, so these are the only files to change.
"""
from pathlib import Path

import pytest

from agentharness.context_files import resolve_context_files
from agentharness.prompt_builder import load_agent_definition

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "agentharness" / "data" / "agents"
CLAUDE_AGENTS = REPO_ROOT / "agentharness" / "data" / "claude-agents"

# The superpowers plugin is installed under a marketplace directory whose name
# is not fixed: `claude-plugins-official` is what ships today,
# `superpowers-marketplace` is the older layout the templates were written
# against. A declared path that hardcodes either one silently matches nothing
# on a machine using the other — and a context file that resolves to nothing
# is dropped without the agent ever knowing it ran without its skill.
MARKETPLACE_LAYOUTS = [
    ("claude-plugins-official", "6.3.0"),
    ("superpowers-marketplace", "1.0.0"),
]

# agent file -> the superpowers skill its context_files entry must resolve to
SUPERPOWERS_CONTEXT = {
    "developer.md": "subagent-driven-development",
    "planner.md": "writing-plans",
    "brainstorm.md": "brainstorming",
}


def _install_skill(home: Path, marketplace: str, version: str, skill: str) -> Path:
    target = (
        home / ".claude" / "plugins" / "cache" / marketplace / "superpowers"
        / version / "skills" / skill / "SKILL.md"
    )
    target.parent.mkdir(parents=True)
    target.write_text(f"# {skill}\n", encoding="utf-8")
    return target


@pytest.mark.parametrize("agent_file,skill", sorted(SUPERPOWERS_CONTEXT.items()))
@pytest.mark.parametrize("marketplace,version", MARKETPLACE_LAYOUTS)
def test_context_file_resolves_under_either_marketplace_layout(
    agent_file, skill, marketplace, version, tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = _install_skill(tmp_path, marketplace, version, skill)
    declared = load_agent_definition(AGENTS / agent_file).context_files

    result = resolve_context_files(declared, agent_file, tmp_path)

    assert [f.resolved_path for f in result.files] == [expected], (
        f"{agent_file}'s context_files glob matched nothing under "
        f"{marketplace}/ — the agent runs without its {skill} skill every time"
    )


def _context_file_instruction(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    start = body.index("context_files")
    return " ".join(body[start : start + 700].split()).lower()


ORCHESTRATORS = ["implement-orchestrator.md", "plan-orchestrator.md", "orchestrator.md"]


@pytest.mark.parametrize("template", ORCHESTRATORS)
def test_orchestrator_stops_when_a_declared_context_file_matches_nothing(template):
    """The orchestrators read `context_files:` by hand and prepend them. With
    no rule for the empty case they prepended nothing and ran the agent
    anyway, so a dead path cost the agent its skill in total silence."""
    instruction = _context_file_instruction(CLAUDE_AGENTS / template)

    assert "no file" in instruction or "nothing" in instruction, (
        f"{template} says nothing about a context path that matches no file"
    )
    assert "stop" in instruction, (
        f"{template} does not tell the orchestrator to stop when a declared "
        "context file is missing — it will silently run the agent without it"
    )


@pytest.mark.parametrize("template", ORCHESTRATORS)
def test_orchestrator_templates_declare_the_name_claude_code_registers_them_under(template):
    """Claude Code registers an agent in `.claude/agents/` by its `name:`
    frontmatter key. These templates carried only `id:`, so `agentharness
    init` installed them and the agent type still did not exist — every
    worker fell back to reading the file and following it by hand."""
    frontmatter = (CLAUDE_AGENTS / template).read_text(encoding="utf-8").split("---")[1]
    names = [
        ln.split(":", 1)[1].strip()
        for ln in frontmatter.splitlines()
        if ln.startswith("name:")
    ]

    assert names == [template[: -len(".md")]], (
        f"{template} must declare `name: {template[:-len('.md')]}` or Claude Code "
        "never registers it as an agent type"
    )


# === the orchestrator agent type may simply not be registered ===

SKILLS = REPO_ROOT / ".claude" / "skills"
ORCHESTRATOR_STEPS = [
    ("implement-next-task", "Run the implementing orchestrator", "\n8."),
    ("plan-next-task", "Run the planning orchestrator", "\n6."),
]


@pytest.mark.parametrize("skill,heading,end", ORCHESTRATOR_STEPS)
def test_skill_says_what_to_do_when_the_orchestrator_agent_type_is_missing(
    skill, heading, end
):
    """`agentharness init` installs the template, but the agent type is not
    always registered in the consuming repo's environment. Real workers found
    it missing and coped by reading the file and following its sections by
    hand — which worked, but only because they improvised. An instruction that
    says "via the Task tool" and stops leaves the next worker to guess, and a
    worker that guesses "skip it" loses the unit of work silently."""
    body = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    step = " ".join(body.split(heading, 1)[1].split(end, 1)[0].split()).lower()

    assert "not available" in step or "unavailable" in step, (
        f"{skill} does not say what to do when the orchestrator agent type "
        "is not registered in this environment"
    )
    assert "read" in step and "follow" in step, (
        f"{skill} names no fallback for a missing agent type"
    )
