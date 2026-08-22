"""Guards the pipeline skills' GitHub-access contract.

These skills run unattended in environments where the `gh` CLI is blocked, so
each one must say how it reaches GitHub and must never instruct the agent to
shell out to `gh`. The failure this prevents is quiet: a skill that reaches for
`gh` does not degrade, it dies — and only in the headless run, never when a
human tries it locally with `gh` on their PATH.

`gh` inside the *scripts* is fine and deliberate: they branch on `USE_GH_API`
internally and are not covered here. This checks only the SKILL.md bash blocks,
which are instructions to the agent itself.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILLS = REPO_ROOT / ".claude" / "skills"

PIPELINE_SKILLS = [
    "automerge-pr",
    "automerge-all",
    "hygiene-pr",
    "hygiene-all",
    "rework-pr",
    "rework-all",
]

# A `gh` command invocation: at the start of a line (indented or not, e.g.
# inside an `if`), or after a pipe/&&/;/$( . `gh_api.sh`, `GH_REPO=`, and prose
# like "the `gh` CLI" are not invocations.
GH_INVOCATION = re.compile(r"(?:^[ \t]*|[;&|]\s*|\$\(\s*)gh\s+[a-z]", re.MULTILINE)
BASH_FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _bash_blocks(text: str) -> list[str]:
    blocks = []
    for body in BASH_FENCE.findall(text):
        # Drop comment lines — they explain, they don't execute.
        blocks.append("\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        ))
    return blocks


@pytest.mark.parametrize("skill", PIPELINE_SKILLS)
def test_skill_documents_its_github_access(skill):
    text = (SOURCE_SKILLS / skill / "SKILL.md").read_text()
    assert "GitHub access" in text, (
        f"{skill}/SKILL.md must state how it reaches GitHub — without a rule, an "
        f"agent falls back to whatever CLAUDE.md says, which is `gh`."
    )


@pytest.mark.parametrize("skill", PIPELINE_SKILLS)
def test_skill_never_tells_the_agent_to_shell_out_to_gh(skill):
    text = (SOURCE_SKILLS / skill / "SKILL.md").read_text()
    offenders = [
        m.group(0).strip()
        for block in _bash_blocks(text)
        for m in GH_INVOCATION.finditer(block)
    ]
    assert not offenders, (
        f"{skill}/SKILL.md runs `gh` directly ({offenders}). Use mcp__github__* "
        f"or .claude/skills/_lib/gh_api.sh — `gh` is blocked where this runs."
    )


@pytest.mark.parametrize("skill", PIPELINE_SKILLS)
def test_skill_names_the_rest_fallback_not_gh(skill):
    # "Use MCP" alone is not enough: the skills also run where MCP is absent,
    # and an unstated fallback becomes `gh` by default.
    text = (SOURCE_SKILLS / skill / "SKILL.md").read_text()
    assert "gh_api.sh" in text, (
        f"{skill}/SKILL.md must name _lib/gh_api.sh as the no-MCP fallback"
    )
