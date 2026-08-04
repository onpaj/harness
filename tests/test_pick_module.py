"""Tests for .claude/skills/arch-review/pick-module.sh.

The real bash script is driven against synthetic maps. `ARCH_NO_PULL=1` is set
everywhere so no test ever touches the network or the git remote.

The behaviours worth pinning down:
  * exactly one well-formed line on stdout, exit 0, on the real map,
  * the map is an ARGUMENT — any map, any repo — and travels in the output line
    so the reviewer is self-sufficient,
  * RETIRED rows are never drawn (they exist only so old references resolve),
  * headings are not parsed — only summary-table rows are,
  * every failure mode exits non-zero with an EMPTY stdout, because the caller
    treats a non-zero exit as "no review this cycle". A malformed line would
    instead spend a whole agent review on nothing.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "arch-review" / "pick-module.sh"
REAL_MAP = REPO_ROOT / "docs" / "architecture" / "module-map.md"

LINE_RE = re.compile(
    r"^Architecture review of module map part #(\d+) — (.+) \(map: (.+)\)$"
)

SYNTHETIC_MAP = """# Application Module Map

## Summary table

| # | Part | Approx. size |
|---|------|--------------|
| 1 | Alpha | PY ~1k |
| 2 | RETIRED — merged into #1 | — |
| 3 | Gamma | PY ~2k |

## 2. RETIRED — merged into #1

A retired part keeps its heading so old references stay resolvable.
"""


def run_picker(*, map_path=None, map_arg=None, part=None):
    """Drive the real script. `map_path` goes through $ARCH_MAP, `map_arg` through argv."""
    env = {"ARCH_NO_PULL": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    if map_path is not None:
        env["ARCH_MAP"] = str(map_path)
    if part is not None:
        env["ARCH_PART"] = str(part)
    argv = [str(SCRIPT)] + ([str(map_arg)] if map_arg is not None else [])
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30)


@pytest.fixture
def synthetic_map(tmp_path):
    path = tmp_path / "module-map.md"
    path.write_text(SYNTHETIC_MAP, encoding="utf-8")
    return path


def test_script_is_executable():
    assert SCRIPT.is_file(), f"{SCRIPT} must exist"
    assert SCRIPT.stat().st_mode & 0o111, "pick-module.sh must be executable"


def test_prints_one_well_formed_line_from_the_real_map():
    # Arrange / Act
    result = run_picker()

    # Assert
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1, "must print exactly one line"
    assert LINE_RE.match(result.stdout.strip()), f"malformed: {result.stdout!r}"


def test_every_drawn_part_is_a_live_row_of_the_real_map():
    # Arrange — the part numbers actually present in the map's summary tables.
    live = {
        m.group(1)
        for line in REAL_MAP.read_text(encoding="utf-8").splitlines()
        if (m := re.match(r"^\|\s*(\d+)\s*\|", line)) and "RETIRED" not in line
    }
    assert live, "the real map must contain summary-table rows"

    # Act
    drawn = {LINE_RE.match(run_picker().stdout.strip()).group(1) for _ in range(60)}

    # Assert
    assert drawn <= live, f"drew parts absent from the map: {drawn - live}"


def test_draws_are_spread_over_many_parts():
    drawn = {LINE_RE.match(run_picker().stdout.strip()).group(1) for _ in range(120)}
    assert len(drawn) > 5, f"selection looks stuck, only drew {drawn}"


def test_never_draws_a_retired_row(synthetic_map):
    # Arrange / Act — 60 draws over a 2-live-row map; a retired row would surface.
    drawn = {
        LINE_RE.match(run_picker(map_path=synthetic_map).stdout.strip()).group(1)
        for _ in range(60)
    }

    # Assert — #2 is RETIRED, and its "## 2." heading must not resurrect it.
    assert drawn == {"1", "3"}, f"expected only live rows, got {drawn}"


def test_part_override_selects_that_exact_part(synthetic_map):
    result = run_picker(map_path=synthetic_map, part=3)

    assert result.returncode == 0, result.stderr
    number, name, _map = LINE_RE.match(result.stdout.strip()).groups()
    assert (number, name) == ("3", "Gamma")


def test_part_override_rejects_a_retired_part(synthetic_map):
    result = run_picker(map_path=synthetic_map, part=2)

    assert result.returncode != 0
    assert result.stdout == "", "a rejected override must print nothing on stdout"


def _git_repo_with_map(tmp_path, *, extra_map=False):
    """A throwaway git repo carrying a map at the conventional location."""
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "module-map.md").write_text(
        SYNTHETIC_MAP, encoding="utf-8"
    )
    if extra_map:
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "module-map.md").write_text(
            SYNTHETIC_MAP, encoding="utf-8"
        )
    subprocess.run(
        ["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


def run_picker_in(cwd, *, argv=()):
    """Run the picker with a given working directory and no map hints at all."""
    return subprocess.run(
        [str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={"ARCH_NO_PULL": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=30,
    )


def test_zero_arg_run_discovers_the_map_of_the_current_repo():
    # Arrange / Act — no argument, no env: the common case of running the skill
    # inside the repository you want audited.
    result = run_picker_in(REPO_ROOT)

    # Assert
    assert result.returncode == 0, result.stderr
    assert LINE_RE.match(result.stdout.strip()).group(3) == str(REAL_MAP)


def test_zero_arg_run_from_a_subdirectory_still_finds_the_repo_map():
    result = run_picker_in(REPO_ROOT / "agentharness" / "data" / "agents")

    assert result.returncode == 0, result.stderr
    assert LINE_RE.match(result.stdout.strip()).group(3) == str(REAL_MAP)


def test_discovery_follows_the_cwd_repo_not_the_scripts_own_repo(tmp_path):
    # Arrange — a foreign repo with its own map. The script lives in THIS repo,
    # so a location-based default would wrongly return this repo's map.
    foreign = _git_repo_with_map(tmp_path)

    # Act
    result = run_picker_in(foreign)

    # Assert
    found = Path(LINE_RE.match(result.stdout.strip()).group(3)).resolve()
    assert found == (foreign / "docs" / "architecture" / "module-map.md").resolve()
    assert found != REAL_MAP.resolve()


def test_ambiguous_discovery_fails_closed_rather_than_guessing(tmp_path):
    # Arrange — two maps, no conventional-path winner.
    repo = tmp_path
    (repo / "a").mkdir()
    (repo / "b").mkdir()
    for sub in ("a", "b"):
        (repo / sub / "module-map.md").write_text(SYNTHETIC_MAP, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)

    # Act
    result = run_picker_in(repo)

    # Assert — guessing between maps would silently audit the wrong thing.
    assert result.returncode != 0
    assert result.stdout == ""
    assert "several module maps" in result.stderr


def test_conventional_location_wins_over_a_stray_map(tmp_path):
    repo = _git_repo_with_map(tmp_path, extra_map=True)

    result = run_picker_in(repo)

    assert result.returncode == 0, result.stderr
    found = Path(LINE_RE.match(result.stdout.strip()).group(3)).resolve()
    assert found == (repo / "docs" / "architecture" / "module-map.md").resolve()


def test_no_map_anywhere_fails_closed_with_a_useful_message(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)

    result = run_picker_in(tmp_path)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "no module map found" in result.stderr
    assert "arch-map" in result.stderr, "must point at how to create one"


def test_map_can_be_passed_as_an_argument(synthetic_map):
    # Arrange / Act — the map is an input, not a constant: a map outside this
    # repository must work, since that is the whole point of the argument.
    result = run_picker(map_arg=synthetic_map)

    # Assert
    assert result.returncode == 0, result.stderr
    assert LINE_RE.match(result.stdout.strip())


def test_argument_wins_over_the_env_variable(tmp_path, synthetic_map):
    # Arrange — an env map that would give a different, recognisable answer.
    other = tmp_path / "other-map.md"
    other.write_text("| # | Part |\n|---|---|\n| 99 | Elsewhere |\n", encoding="utf-8")

    # Act
    result = run_picker(map_path=other, map_arg=synthetic_map)

    # Assert
    assert "Elsewhere" not in result.stdout, "argv must take precedence over $ARCH_MAP"
    assert result.stdout.strip().endswith(f"(map: {synthetic_map})")


def test_output_carries_the_resolved_absolute_map_path(synthetic_map, tmp_path):
    # Arrange — a relative path, so resolution is actually exercised.
    relative = synthetic_map.relative_to(tmp_path)

    # Act — run from the map's own directory so the relative path resolves.
    result = subprocess.run(
        [str(SCRIPT), str(relative)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"ARCH_NO_PULL": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=30,
    )

    # Assert — the reviewer opens this path itself, so it must not be relative.
    assert result.returncode == 0, result.stderr
    emitted = LINE_RE.match(result.stdout.strip()).group(3)
    assert Path(emitted).is_absolute(), f"map path must be absolute, got {emitted!r}"
    assert Path(emitted).resolve() == synthetic_map.resolve()


def test_missing_map_argument_fails_closed(tmp_path):
    result = run_picker(map_arg=tmp_path / "nope.md")

    assert result.returncode != 0
    assert result.stdout == "", "a failure must print nothing on stdout"


def test_missing_map_fails_closed(tmp_path):
    result = run_picker(map_path=tmp_path / "nope.md")

    assert result.returncode != 0
    assert result.stdout == "", "a failure must print nothing on stdout"


def test_map_without_rows_fails_closed(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# Nothing here\n", encoding="utf-8")

    result = run_picker(map_path=empty)

    assert result.returncode != 0
    assert result.stdout == ""
