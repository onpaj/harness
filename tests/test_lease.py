"""Tests for _lib/lease.sh -- the cross-machine mutual-exclusion lease.

These run against REAL git repositories (a bare "origin" plus two clones
standing in for two machines) rather than a stubbed `git`. The whole point
of storing the lease as a git ref is that ref updates are atomic on the
server, and only a real remote actually exercises that: a stub would
happily let both racers "win" and the test would prove nothing.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEASE_SH = REPO_ROOT / ".claude" / "skills" / "_lib" / "lease.sh"


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def origin(tmp_path):
    """A bare repo standing in for GitHub."""
    path = tmp_path / "origin.git"
    path.mkdir()
    _git(path, "init", "--bare", "--initial-branch=main")
    return path


@pytest.fixture
def clone_factory(tmp_path, origin):
    """Make independent clones of `origin` -- each one is a 'machine'."""
    counter = {"n": 0}

    def make():
        counter["n"] += 1
        path = tmp_path / f"clone{counter['n']}"
        _git(tmp_path, "clone", "--quiet", str(origin), str(path))
        _git(path, "config", "user.email", "test@example.com")
        _git(path, "config", "user.name", "test")
        return path

    return make


BASE_PATH = "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"


def run_lease(cwd, *args, holder=None, now=None, expect=None,
              path_prefix=None, env_extra=None):
    env = {
        "PATH": f"{path_prefix}:{BASE_PATH}" if path_prefix else BASE_PATH,
        "HOME": str(cwd),
    }
    if holder is not None:
        env["AGENT_LEASE_HOLDER"] = holder
    if now is not None:
        env["LEASE_NOW_OVERRIDE"] = now
    env.update(env_extra or {})
    proc = subprocess.run(
        [str(LEASE_SH), *args], cwd=cwd, capture_output=True, text=True, env=env
    )
    if expect is not None:
        assert proc.returncode == expect, (
            f"expected exit {expect}, got {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc


# === acquire ===

def test_acquire_on_a_free_lease_succeeds(clone_factory):
    repo = clone_factory()
    proc = run_lease(repo, "acquire", "feat-1", holder="worker-a", expect=0)
    payload = json.loads(proc.stdout)
    assert payload["holder"] == "worker-a"
    assert payload["lease_id"] == "feat-1"


def test_second_worker_cannot_acquire_a_held_lease(clone_factory):
    """The core guarantee: worker B is refused while A's lease is live."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-1", holder="worker-a", expect=0)

    proc = run_lease(b, "acquire", "feat-1", holder="worker-b", expect=3)
    payload = json.loads(proc.stdout)
    assert payload["acquired"] is False
    assert payload["holder"] == "worker-a"


def test_a_lease_is_visible_from_a_different_clone(clone_factory):
    """Cross-machine visibility -- the lease lives on origin, not locally."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-7", holder="worker-a", expect=0)

    proc = run_lease(b, "status", "feat-7", expect=0)
    status = json.loads(proc.stdout)
    assert status["held"] is True
    assert status["holder"] == "worker-a"


def test_expired_lease_can_be_taken_over(clone_factory):
    """A worker that died must not wedge the issue forever."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-2", "1", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)

    # 90 minutes later, well past the 1-minute TTL.
    proc = run_lease(b, "acquire", "feat-2", holder="worker-b",
                     now="2026-01-01T01:30:00Z", expect=0)
    assert json.loads(proc.stdout)["holder"] == "worker-b"


def test_unexpired_lease_is_not_taken_over_just_because_time_passed(clone_factory):
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-3", "120", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)

    # 30 minutes in: still well inside the 120-minute TTL. This is the
    # regression case -- under the old commit-age rule this worker would
    # have been declared dead purely for not having committed lately.
    run_lease(b, "acquire", "feat-3", holder="worker-b",
              now="2026-01-01T00:30:00Z", expect=3)


def test_reacquiring_our_own_lease_succeeds(clone_factory):
    """Idempotent for the same holder -- a retried step must not deadlock."""
    a = clone_factory()
    run_lease(a, "acquire", "feat-4", holder="worker-a", expect=0)
    run_lease(a, "acquire", "feat-4", holder="worker-a", expect=0)


def test_leases_for_different_issues_are_independent(clone_factory):
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-10", holder="worker-a", expect=0)
    run_lease(b, "acquire", "feat-11", holder="worker-b", expect=0)


# === release ===

def test_release_frees_the_lease_for_another_worker(clone_factory):
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-5", holder="worker-a", expect=0)
    run_lease(a, "release", "feat-5", holder="worker-a", expect=0)

    run_lease(b, "acquire", "feat-5", holder="worker-b", expect=0)


def test_release_refuses_to_drop_someone_elses_live_lease(clone_factory):
    """Releasing another worker's lease would hand its work to a third."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-6", holder="worker-a", expect=0)

    run_lease(b, "release", "feat-6", holder="worker-b", expect=3)

    proc = run_lease(b, "status", "feat-6", expect=0)
    assert json.loads(proc.stdout)["holder"] == "worker-a"


def test_release_of_an_absent_lease_is_a_no_op(clone_factory):
    """Cleanup runs on every exit path, including ones that never acquired."""
    a = clone_factory()
    proc = run_lease(a, "release", "feat-99", holder="worker-a", expect=0)
    assert json.loads(proc.stdout)["released"] is True


# === renew ===

def test_renew_extends_a_lease_we_hold(clone_factory):
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-8", "10", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)
    run_lease(a, "renew", "feat-8", "120", holder="worker-a",
              now="2026-01-01T00:05:00Z", expect=0)

    # 30 minutes in, the original 10-minute TTL would have lapsed; the
    # renewal must still be holding B off.
    run_lease(b, "acquire", "feat-8", holder="worker-b",
              now="2026-01-01T00:30:00Z", expect=3)


def test_renew_fails_once_the_lease_was_stolen(clone_factory):
    """A worker must learn it lost exclusivity rather than assume it kept it."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-9", "1", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)
    run_lease(b, "acquire", "feat-9", "120", holder="worker-b",
              now="2026-01-01T01:00:00Z", expect=0)

    run_lease(a, "renew", "feat-9", holder="worker-a",
              now="2026-01-01T01:01:00Z", expect=3)


def test_renew_without_a_lease_fails(clone_factory):
    a = clone_factory()
    run_lease(a, "renew", "feat-12", holder="worker-a", expect=3)


# === status ===

def test_status_of_an_absent_lease(clone_factory):
    a = clone_factory()
    proc = run_lease(a, "status", "feat-404", expect=0)
    status = json.loads(proc.stdout)
    assert status["state"] == "absent"
    assert status["held"] is False


def test_status_reports_expired_separately_from_held(clone_factory):
    a = clone_factory()
    run_lease(a, "acquire", "feat-13", "1", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)
    proc = run_lease(a, "status", "feat-13", now="2026-01-01T01:00:00Z", expect=0)
    status = json.loads(proc.stdout)
    assert status["state"] == "expired"
    assert status["held"] is False


# === usage errors ===

def test_no_command_is_a_usage_error(clone_factory):
    run_lease(clone_factory(), expect=1)


def test_missing_lease_id_is_a_usage_error(clone_factory):
    run_lease(clone_factory(), "acquire", expect=1)


def test_lease_id_with_ref_unsafe_characters_is_rejected(clone_factory):
    run_lease(clone_factory(), "acquire", "feat-1/../../head", expect=1)


def test_non_numeric_ttl_is_a_usage_error(clone_factory):
    run_lease(clone_factory(), "acquire", "feat-1", "ten", expect=1)


def test_zero_ttl_is_a_usage_error(clone_factory):
    """A zero TTL would expire instantly and provide no exclusion at all."""
    run_lease(clone_factory(), "acquire", "feat-1", "0", expect=1)


# === genuine concurrency ===

def test_only_one_of_many_simultaneous_workers_acquires(clone_factory):
    """The invariant the whole design exists for.

    Eight workers on eight separate clones race for the same lease at the
    same moment. Whether a given loser is refused by the state check (it
    read the winner's lease) or by the push itself (it read an absent lease
    and lost the compare-and-set), exactly one may come away holding it.
    """
    import threading

    clones = [clone_factory() for _ in range(8)]
    results = {}
    barrier = threading.Barrier(len(clones))

    def attempt(index, repo):
        barrier.wait()
        proc = run_lease(repo, "acquire", "feat-race", holder=f"worker-{index}")
        results[index] = proc.returncode

    threads = [
        threading.Thread(target=attempt, args=(i, repo))
        for i, repo in enumerate(clones)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [i for i, code in results.items() if code == 0]
    assert len(winners) == 1, f"expected exactly one winner, got {winners}"
    assert all(results[i] == 3 for i in results if i not in winners), (
        f"every loser must report contention (exit 3), got {results}"
    )

    # And the ref really does name the winner.
    status = json.loads(run_lease(clones[0], "status", "feat-race", expect=0).stdout)
    assert status["holder"] == f"worker-{winners[0]}"


# === holder identity across separate shells ===
#
# A skill acquires in one bash block and releases in another, and each block
# is its own process -- an exported variable cannot bridge them. These tests
# pin the file-backed identity that does, and the asymmetry that keeps it
# from becoming an impersonation hole.


def test_release_works_from_a_later_shell_without_any_env(clone_factory):
    """The realistic skill flow: acquire, then release with nothing passed."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-20", expect=0)          # no AGENT_LEASE_HOLDER
    run_lease(a, "release", "feat-20", expect=0)          # no AGENT_LEASE_HOLDER

    run_lease(b, "acquire", "feat-20", holder="worker-b", expect=0)


def test_renew_works_from_a_later_shell_without_any_env(clone_factory):
    a = clone_factory()
    run_lease(a, "acquire", "feat-21", "10", now="2026-01-01T00:00:00Z", expect=0)
    run_lease(a, "renew", "feat-21", "120", now="2026-01-01T00:05:00Z", expect=0)


def test_a_second_acquire_in_the_same_checkout_cannot_impersonate_the_first(clone_factory):
    """The hole this design closes.

    Both workers run in the SAME checkout, so both can see the recorded
    holder id. `acquire` must never read it -- if it did, worker two would
    adopt worker one's identity, decide the live lease was its own, and
    take it over.
    """
    repo = clone_factory()
    run_lease(repo, "acquire", "feat-22", expect=0)

    # Same directory, same recorded id on disk, no env override.
    run_lease(repo, "acquire", "feat-22", expect=3)


def test_release_from_a_different_checkout_cannot_drop_our_lease(clone_factory):
    """Without the recorded id (different clone), release is refused."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-23", expect=0)

    run_lease(b, "release", "feat-23", expect=3)
    assert json.loads(run_lease(a, "status", "feat-23", expect=0).stdout)["held"] is True


def test_stale_recorded_id_does_not_let_us_steal_a_new_holders_lease(clone_factory):
    """A crashed run leaves its id on disk. A later worker in that checkout
    must not use it to release a lease that has since passed to someone
    else."""
    a, b = clone_factory(), clone_factory()
    run_lease(a, "acquire", "feat-24", "1", now="2026-01-01T00:00:00Z", expect=0)
    # a's id is now recorded in a's checkout, and its lease expires.
    run_lease(b, "acquire", "feat-24", "120", holder="worker-b",
              now="2026-01-01T01:00:00Z", expect=0)

    run_lease(a, "release", "feat-24", now="2026-01-01T01:01:00Z", expect=3)


# === release is a compare-and-set too ===

# A `git` that, exactly once, lets a second worker legitimately take the
# lease over in the instant between our read of the ref and our delete of
# it. That TOCTOU window is the only way a release can destroy a lease that
# is no longer ours, so it is the one thing worth simulating precisely.
GIT_TAKEOVER_SHIM = """\
#!/usr/bin/env bash
for a in "$@"; do
  if [ "$a" = "--delete" ] && [ ! -f "$SHIM_MARKER" ]; then
    : > "$SHIM_MARKER"
    ( cd "$SHIM_THIEF_REPO" \\
      && AGENT_LEASE_HOLDER=thief LEASE_NOW_OVERRIDE="$SHIM_NOW" \\
         "$SHIM_LEASE_SH" acquire "$SHIM_LEASE_ID" 120 ) >/dev/null 2>&1 || true
    break
  fi
done
exec /usr/bin/git "$@"
"""


@pytest.fixture
def takeover_shim(tmp_path, clone_factory):
    """PATH prefix + env that stage a mid-release takeover by another clone."""
    def stage(lease_id, now):
        thief = clone_factory()
        shim_dir = tmp_path / f"shim-{lease_id}"
        shim_dir.mkdir()
        git_shim = shim_dir / "git"
        git_shim.write_text(GIT_TAKEOVER_SHIM)
        git_shim.chmod(0o755)
        return str(shim_dir), {
            "SHIM_MARKER": str(tmp_path / f"marker-{lease_id}"),
            "SHIM_THIEF_REPO": str(thief),
            "SHIM_LEASE_SH": str(LEASE_SH),
            "SHIM_LEASE_ID": lease_id,
            "SHIM_NOW": now,
        }

    return stage


def test_release_does_not_destroy_a_lease_taken_over_since_we_read_it(
    clone_factory, takeover_shim
):
    """The delete must be a compare-and-set, not an unconditional wipe.

    Our own lease lapses, we release it, and in the gap between reading the
    ref and deleting it a second worker legitimately takes it over. An
    unconditional `git push origin :ref` would delete that new holder's
    lease -- leaving it working without exclusivity while a third worker is
    free to acquire, which is the exact collision this library prevents.
    """
    a = clone_factory()
    run_lease(a, "acquire", "feat-30", "1", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)

    path_prefix, env_extra = takeover_shim("feat-30", "2026-01-01T00:02:00Z")
    proc = run_lease(a, "release", "feat-30", holder="worker-a",
                     now="2026-01-01T00:02:00Z",
                     path_prefix=path_prefix, env_extra=env_extra)

    assert json.loads(proc.stdout)["released"] is False
    status = json.loads(run_lease(a, "status", "feat-30",
                                  now="2026-01-01T00:03:00Z", expect=0).stdout)
    assert status["held"] is True
    assert status["holder"] == "thief"


def test_release_reports_the_takeover_rather_than_a_bare_failure(
    clone_factory, takeover_shim
):
    a = clone_factory()
    run_lease(a, "acquire", "feat-31", "1", holder="worker-a",
              now="2026-01-01T00:00:00Z", expect=0)

    path_prefix, env_extra = takeover_shim("feat-31", "2026-01-01T00:02:00Z")
    proc = run_lease(a, "release", "feat-31", holder="worker-a",
                     now="2026-01-01T00:02:00Z",
                     path_prefix=path_prefix, env_extra=env_extra)

    assert json.loads(proc.stdout)["holder"] == "thief"


# === an unreachable origin is not an absent lease ===

def _break_origin(repo):
    _git(repo, "remote", "set-url", "origin", str(repo / "no-such-origin.git"))


def test_release_does_not_claim_success_when_origin_is_unreachable(clone_factory):
    """`released: true` must mean the remote ref is gone. Reporting it after
    a failed push tells the caller the lease was dropped when it is still
    held remotely until its TTL runs out."""
    a = clone_factory()
    run_lease(a, "acquire", "feat-32", holder="worker-a", expect=0)
    _break_origin(a)

    proc = run_lease(a, "release", "feat-32", holder="worker-a")

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["released"] is False
    assert "origin" in payload["reason"]


def test_release_of_an_absent_lease_still_fails_when_origin_is_unreachable(clone_factory):
    """Without a reachable origin we cannot tell 'no lease' from 'cannot
    see the lease', and must not guess the reassuring one."""
    a = clone_factory()
    _break_origin(a)

    proc = run_lease(a, "release", "feat-33", holder="worker-a")

    assert proc.returncode != 0
    assert json.loads(proc.stdout)["released"] is False


def test_renew_says_origin_is_unreachable_rather_than_lease_lost(clone_factory):
    """'Someone stole your lease' and 'the network blipped' call for very
    different reactions from the caller."""
    a = clone_factory()
    run_lease(a, "acquire", "feat-34", holder="worker-a", expect=0)
    _break_origin(a)

    proc = run_lease(a, "renew", "feat-34", holder="worker-a")

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["renewed"] is False
    assert "origin" in payload["reason"]


def test_status_reports_unknown_when_origin_is_unreachable(clone_factory):
    a = clone_factory()
    run_lease(a, "acquire", "feat-35", holder="worker-a", expect=0)
    _break_origin(a)

    payload = json.loads(run_lease(a, "status", "feat-35", expect=0).stdout)

    assert payload["state"] == "unknown"
    assert payload["held"] is False


def test_status_of_a_reachable_lease_reports_the_fetch_succeeded(clone_factory):
    a = clone_factory()
    run_lease(a, "acquire", "feat-36", holder="worker-a", expect=0)

    payload = json.loads(run_lease(a, "status", "feat-36", expect=0).stdout)

    assert payload["state"] == "held"
    assert payload["fetch_ok"] is True


# === holder identity is per checkout, not per working directory ===

def test_release_from_a_subdirectory_recognises_our_own_lease(clone_factory):
    """acquire runs from the repo root and release from wherever the skill
    happens to be; both must resolve to the same recorded identity."""
    a = clone_factory()
    run_lease(a, "acquire", "feat-37", expect=0)
    subdir = a / "nested" / "deeper"
    subdir.mkdir(parents=True)

    proc = run_lease(subdir, "release", "feat-37", expect=0)

    assert json.loads(proc.stdout)["released"] is True


def test_a_lost_acquire_race_keeps_the_earlier_holder_record(clone_factory):
    """A second acquire in the same checkout is correctly refused -- but it
    must not take the first worker's recorded identity down with it, or the
    live lease becomes unreleasable until its TTL expires."""
    a = clone_factory()
    run_lease(a, "acquire", "feat-38", expect=0)

    run_lease(a, "acquire", "feat-38", expect=3)

    proc = run_lease(a, "release", "feat-38", expect=0)
    assert json.loads(proc.stdout)["released"] is True
