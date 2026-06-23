"""Tests for scripts/ensure_pr_linked.sh.

The real bash script is driven through a fake `gh` placed on PATH. The stub keeps
PR state (labels + body) in a JSON file across the multiple `gh` calls a single
script run makes, so we can assert end-to-end behaviour without touching GitHub.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ensure_pr_linked.sh"

# A fake `gh` that mutates/reads a JSON state file given via $GH_FAKE_STATE.
FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys

state_path = os.environ["GH_FAKE_STATE"]
with open(state_path) as fh:
    state = json.load(fh)
args = sys.argv[1:]
state.setdefault("calls", []).append(args)

def save():
    with open(state_path, "w") as fh:
        json.dump(state, fh)

if args[:2] == ["pr", "edit"]:
    if "--add-label" in args:
        label = args[args.index("--add-label") + 1]
        if not state.get("label_wont_land") and label not in state["labels"]:
            state["labels"].append(label)
    if "--body" in args:
        state["body"] = args[args.index("--body") + 1]
    save()
    sys.exit(0)

if args[:2] == ["pr", "view"]:
    save()
    if "labels" in args:
        print("\\n".join(state["labels"]))
    elif "body" in args:
        print(state["body"])
    sys.exit(0)

save()
sys.exit(0)
'''


@pytest.fixture
def run_script(tmp_path):
    """Return a callable that runs the script with a fake `gh` and given state."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    state_path = tmp_path / "state.json"

    def _run(pr, issue, *, labels=None, body="", label_wont_land=False):
        state = {
            "labels": list(labels or []),
            "body": body,
            "label_wont_land": label_wont_land,
            "calls": [],
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["GH_FAKE_STATE"] = str(state_path)

        proc = subprocess.run(
            ["bash", str(SCRIPT), pr, issue],
            env=env,
            capture_output=True,
            text=True,
        )
        final_state = json.loads(state_path.read_text(encoding="utf-8"))
        return proc, final_state

    return _run


def test_adds_agent_label_when_missing(run_script):
    proc, state = run_script("42", "7", labels=[], body="Closes #7")

    assert proc.returncode == 0, proc.stderr
    assert "agent" in state["labels"]


def test_label_add_is_idempotent_when_already_present(run_script):
    proc, state = run_script("42", "7", labels=["agent"], body="Closes #7")

    assert proc.returncode == 0, proc.stderr
    assert state["labels"].count("agent") == 1


def test_injects_closes_when_missing_preserving_body(run_script):
    original = "## What\nSome detail\n\n## Code review\nlooks good"
    proc, state = run_script("42", "7", labels=["agent"], body=original)

    assert proc.returncode == 0, proc.stderr
    assert state["body"].startswith("Closes #7")
    # Existing body content is preserved beneath the injected link.
    assert original in state["body"]


def test_leaves_body_untouched_when_link_present(run_script):
    for body in ("Closes #7", "fixes #7", "This resolves #7 nicely"):
        proc, state = run_script("42", "7", labels=["agent"], body=body)
        assert proc.returncode == 0, proc.stderr
        assert state["body"] == body


def test_does_not_treat_superset_issue_number_as_link(run_script):
    # Body references #70, but the tracking issue is #7 — must still inject.
    proc, state = run_script("42", "7", labels=["agent"], body="Closes #70")

    assert proc.returncode == 0, proc.stderr
    assert state["body"].startswith("Closes #7\n")


def test_rejects_non_numeric_issue(run_script):
    proc, _ = run_script("42", "abc", labels=["agent"], body="")

    assert proc.returncode == 2
    assert "numeric" in proc.stderr


def test_hard_fails_when_label_cannot_land(run_script):
    proc, _ = run_script("42", "7", labels=[], body="Closes #7", label_wont_land=True)

    assert proc.returncode == 1
    assert "agent label missing" in proc.stderr


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK), "scripts/ensure_pr_linked.sh must be executable"
