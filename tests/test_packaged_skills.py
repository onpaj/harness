"""Guards for the skills shipped by `agentharness init`.

`agentharness/data/skills/` is the real, packaged source that `init` copies into a
consumer repo's `.claude/skills/`. It must:
  * be real files, never a symlink — symlinks ship nothing from a pip install,
  * mirror the full set of skills in the repo's `.claude/skills/`,
  * stay byte-identical to that source (so the shipped copy never drifts),
  * carry the oneshot skill's `ensure_pr_linked.sh` (the pr-linking step is
    mandatory when oneshot runs in a consumer repo — see #128).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_SKILLS = REPO_ROOT / "agentharness" / "data" / "skills"
SOURCE_SKILLS = REPO_ROOT / ".claude" / "skills"


def _skill_dirs(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.is_dir()}


def test_data_skills_is_not_a_symlink():
    assert DATA_SKILLS.is_dir() and not DATA_SKILLS.is_symlink(), (
        "agentharness/data/skills must be a real directory, not a symlink — "
        "symlinks are not preserved in a pip-installed wheel."
    )
    for child in DATA_SKILLS.rglob("*"):
        assert not child.is_symlink(), f"{child} must not be a symlink"


def test_ships_the_full_skill_set():
    assert _skill_dirs(DATA_SKILLS) == _skill_dirs(SOURCE_SKILLS), (
        "packaged skills must mirror .claude/skills exactly"
    )


def test_pr_linking_script_ships_with_oneshot():
    script = DATA_SKILLS / "oneshot" / "ensure_pr_linked.sh"
    assert script.is_file(), (
        "ensure_pr_linked.sh must ship inside the oneshot skill so the pr-linking "
        "step works when oneshot runs in a consumer repo (#128)"
    )


def test_packaged_skills_match_their_source():
    for skill in _skill_dirs(SOURCE_SKILLS):
        src, packaged = SOURCE_SKILLS / skill, DATA_SKILLS / skill
        src_files = {p.relative_to(src): p.read_bytes() for p in src.rglob("*") if p.is_file()}
        pkg_files = {p.relative_to(packaged): p.read_bytes() for p in packaged.rglob("*") if p.is_file()}
        assert src_files == pkg_files, (
            f"packaged skill '{skill}' has drifted from .claude/skills/{skill} — "
            "re-copy it so the shipped copy stays in sync."
        )
