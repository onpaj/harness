"""Tests for the arch-map skill's shell helpers.

`survey.sh` measures a repository so a map can be cut from real numbers, and
`check-map.sh` validates a map against the contract and against the repo it
claims to describe.

The behaviours worth pinning down:
  * the survey is language-agnostic and respects .gitignore (it asks git),
  * ERRORs mean the map LIES about a boundary and must fail the run; WARNINGs
    are judgement calls and must not,
  * both `Owns:` notations parse — inline and bullet list,
  * notation that cannot be resolved from the repo root (ellipsis shorthand,
    URL routes, template placeholders) is never reported as a broken boundary.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / ".claude" / "skills" / "arch-map"
SURVEY = SKILL / "survey.sh"
CHECK = SKILL / "check-map.sh"
REAL_MAP = REPO_ROOT / "docs" / "architecture" / "module-map.md"

ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}


def run(script, *args, cwd=None):
    return subprocess.run(
        [str(script), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=ENV,
        timeout=120,
    )


def make_repo(tmp_path, map_text, *, files=("src/app.py",)):
    """A throwaway git repo with a map and some source files."""
    for rel in files:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
    map_path = tmp_path / "docs" / "architecture" / "module-map.md"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(map_text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    return map_path


def map_with(owns_block, *, extra=""):
    return f"""# Application Module Map

## Summary table

| # | Part | Approx. size |
|---|------|--------------|
| 1 | Alpha | PY ~1 |

## 1. Alpha

**Purpose:** the only part.

{owns_block}

**Depends on:** nothing.
{extra}
"""


# ------------------------------------------------------------------- survey --


def test_scripts_are_executable():
    for script in (SURVEY, CHECK):
        assert script.is_file(), f"{script} must exist"
        assert script.stat().st_mode & 0o111, f"{script.name} must be executable"


def test_survey_reports_the_repo_it_is_run_in():
    result = run(SURVEY, cwd=REPO_ROOT)

    assert result.returncode == 0, result.stderr
    assert f"root: {REPO_ROOT}" in result.stdout
    assert "python" in result.stdout, "ecosystem detection should see pyproject.toml"
    assert "== LOC by directory, depth 1 ==" in result.stdout
    assert "agentharness/" in result.stdout


def test_survey_flags_an_existing_map():
    result = run(SURVEY, cwd=REPO_ROOT)

    assert "docs/architecture/module-map.md" in result.stdout
    assert "(none — this is a first cut)" not in result.stdout


def test_survey_reports_a_first_cut_when_no_map_exists(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)

    result = run(SURVEY, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "(none — this is a first cut)" in result.stdout


def test_survey_ignores_gitignored_build_output(tmp_path):
    # Arrange — a large ignored tree that would dominate the numbers if counted.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("y\n" * 5000, encoding="utf-8")
    (tmp_path / ".gitignore").write_text("dist/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)

    # Act
    result = run(SURVEY, tmp_path)

    # Assert
    assert result.returncode == 0, result.stderr
    assert "dist/" not in result.stdout, "gitignored build output must not be measured"


def test_survey_fails_when_there_is_no_source(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)

    result = run(SURVEY, tmp_path)

    assert result.returncode != 0
    assert "no source files" in result.stderr


# ---------------------------------------------------------------- check-map --


def test_check_passes_on_this_repos_real_map():
    result = run(CHECK, REAL_MAP)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "errors: 0" in result.stdout


def test_inline_owns_notation_is_accepted(tmp_path):
    # Arrange — `**Owns:** `path`` on one line, as opposed to a bullet list.
    map_path = make_repo(tmp_path, map_with("**Owns:** `src/`"))

    # Act
    result = run(CHECK, map_path)

    # Assert
    assert result.returncode == 0, result.stdout
    assert "errors: 0" in result.stdout


def test_bullet_owns_notation_is_accepted(tmp_path):
    map_path = make_repo(tmp_path, map_with("**Owns:**\n- `src/`"))

    result = run(CHECK, map_path)

    assert result.returncode == 0, result.stdout


def test_missing_owns_is_an_error(tmp_path):
    # Arrange — a part with no boundary at all.
    map_path = make_repo(tmp_path, map_with("**Purpose restated:** nothing owned."))

    # Act
    result = run(CHECK, map_path)

    # Assert — without Owns, a review of this part has nothing scoping it.
    assert result.returncode != 0
    assert "has no 'Owns:' paths" in result.stdout


def test_dead_owns_path_is_an_error(tmp_path):
    map_path = make_repo(tmp_path, map_with("**Owns:**\n- `src/`\n- `does/not/exist/`"))

    result = run(CHECK, map_path)

    assert result.returncode != 0
    assert "dead Owns: path" in result.stdout


def test_stale_path_in_prose_is_only_a_warning(tmp_path):
    # Arrange — an honest negative statement about a path that does not exist.
    map_path = make_repo(
        tmp_path,
        map_with("**Owns:**\n- `src/`", extra="\nThere is no `docs/adr/` directory.\n"),
    )

    # Act
    result = run(CHECK, map_path)

    # Assert — prose is documentation, not a machine-read boundary.
    assert result.returncode == 0, result.stdout
    assert "stale path in prose" in result.stdout
    assert "errors: 0" in result.stdout


def test_duplicate_part_numbers_are_an_error(tmp_path):
    text = map_with("**Owns:**\n- `src/`").replace(
        "| 1 | Alpha | PY ~1 |", "| 1 | Alpha | PY ~1 |\n| 1 | Beta | PY ~1 |"
    )
    map_path = make_repo(tmp_path, text)

    result = run(CHECK, map_path)

    assert result.returncode != 0
    assert "appears in more than one row" in result.stdout


def test_row_without_a_section_is_an_error(tmp_path):
    text = map_with("**Owns:**\n- `src/`").replace(
        "| 1 | Alpha | PY ~1 |", "| 1 | Alpha | PY ~1 |\n| 2 | Ghost | PY ~1 |"
    )
    map_path = make_repo(tmp_path, text)

    result = run(CHECK, map_path)

    assert result.returncode != 0
    assert "no '## 2.' section" in result.stdout


def test_retired_rows_need_no_section(tmp_path):
    text = map_with("**Owns:**\n- `src/`").replace(
        "| 1 | Alpha | PY ~1 |",
        "| 1 | Alpha | PY ~1 |\n| 2 | RETIRED — merged into #1 | — |",
    )
    map_path = make_repo(tmp_path, text)

    result = run(CHECK, map_path)

    assert result.returncode == 0, result.stdout
    assert "2 total, 1 live" in result.stdout


@pytest.mark.parametrize(
    "token",
    [
        ".../Features/Deep/Nested/",  # ellipsis shorthand
        "/catalog/*",  # a URL route, not a file
        "artifacts/{feature_id}/state.json",  # template placeholder
    ],
)
def test_unresolvable_notation_is_never_a_broken_boundary(tmp_path, token):
    map_path = make_repo(tmp_path, map_with(f"**Owns:**\n- `src/`\n- `{token}`"))

    result = run(CHECK, map_path)

    assert result.returncode == 0, f"{token!r} wrongly reported:\n{result.stdout}"


def test_glob_owns_path_resolves_to_its_directory(tmp_path):
    # Arrange — `src/*.py` is a claim about src/, which exists.
    map_path = make_repo(tmp_path, map_with("**Owns:**\n- `src/*.py`"))

    result = run(CHECK, map_path)

    assert result.returncode == 0, result.stdout


def test_unassigned_directory_is_a_warning_not_an_error(tmp_path):
    map_path = make_repo(
        tmp_path,
        map_with("**Owns:**\n- `src/`"),
        files=("src/app.py", "unmapped/thing.py"),
    )

    result = run(CHECK, map_path)

    assert result.returncode == 0, "unmapped code is a judgement call, not a lie"
    assert "unassigned: unmapped/" in result.stdout


def test_directory_covered_by_an_ancestor_is_not_unassigned(tmp_path):
    # Arrange — the map owns `src/`; `src/deep/` needs no separate mention.
    map_path = make_repo(
        tmp_path,
        map_with("**Owns:**\n- `src/`"),
        files=("src/app.py", "src/deep/inner.py"),
    )

    result = run(CHECK, map_path)

    assert result.returncode == 0, result.stdout
    assert "unassigned: src/deep" not in result.stdout


def test_map_with_no_rows_fails(tmp_path):
    map_path = make_repo(tmp_path, "# Empty map\n\nNo tables here.\n")

    result = run(CHECK, map_path)

    assert result.returncode != 0
    assert "no summary-table rows" in result.stdout


def test_missing_map_fails(tmp_path):
    result = run(CHECK, tmp_path / "nope.md")

    assert result.returncode != 0
    assert "no module map" in result.stderr
