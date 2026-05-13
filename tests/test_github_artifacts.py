"""Unit tests for agentharness.github_artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentharness.github_artifacts import GitHubArtifactStore

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_OWNER = "test-owner"
_REPO = "test-repo"
_FEATURE_ID = "feat-20260427-abc123"
_CLONE_DIR = Path("/tmp/worktrees-test")
_CLONE_ROOT = _CLONE_DIR / _FEATURE_ID


def _make_store(clone_dir: Path = _CLONE_DIR) -> GitHubArtifactStore:
    return GitHubArtifactStore(
        owner=_OWNER,
        repo=_REPO,
        feature_id=_FEATURE_ID,
        clone_dir=clone_dir,
    )


def _proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    """Build a mock Process object."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_builds_correct_paths() -> None:
    config = MagicMock()
    config.github.owner = "org"
    config.github.runs_repo = "runs"
    config.github.clone_dir = ".worktrees"

    store = GitHubArtifactStore.from_config(config, "feat-xyz")

    assert store._owner == "org"
    assert store._repo == "runs"
    assert store._feature_id == "feat-xyz"
    assert store._clone_dir == Path(".worktrees")
    assert store._clone_root == Path(".worktrees") / "feat-xyz"


# ---------------------------------------------------------------------------
# get_work_dir
# ---------------------------------------------------------------------------


def test_get_work_dir_returns_clone_root() -> None:
    store = _make_store()
    assert store.get_work_dir() == _CLONE_ROOT


# ---------------------------------------------------------------------------
# upload — git command sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_runs_git_commands_in_order() -> None:
    store = _make_store()

    recorded_calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        # Strip the "git" prefix so we record only the sub-command args.
        recorded_calls.append(args[1:])  # args = ("git", "-C", ..., subcommand, ...)
        return _proc(returncode=0, stdout=b"")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),   # clone already present
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text"),
        patch.object(Path, "write_bytes"),
    ):
        await store.upload("artifacts/feat-x/spec.r1.md", "hello")

    # Extract the git sub-command names from the recorded calls.
    subcommands = [args[args.index("-C") + 2] if "-C" in args else args[0] for args in recorded_calls]

    assert subcommands[0] == "fetch"
    assert subcommands[1] == "checkout"
    assert subcommands[2] == "add"
    assert subcommands[3] == "commit"
    assert subcommands[4] == "push"


@pytest.mark.asyncio
async def test_upload_skips_commit_when_nothing_to_commit() -> None:
    """upload() must not raise when git commit reports nothing to commit."""
    store = _make_store()

    call_count = 0

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        sub_args = args[1:]  # drop "git"
        is_commit = "commit" in sub_args
        returncode = 1 if is_commit else 0
        stderr = b"nothing to commit, working tree clean" if is_commit else b""
        return _proc(returncode=returncode, stdout=b"", stderr=stderr)

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text"),
    ):
        # Should not raise.
        await store.upload("artifacts/feat-x/spec.r1.md", "hello")


@pytest.mark.asyncio
async def test_upload_clones_repo_when_not_present(tmp_path: Path) -> None:
    """When the clone root is absent, git clone is invoked first."""
    clone_dir = tmp_path / "cache"
    store = _make_store(clone_dir=clone_dir)

    recorded_calls: list[tuple[str, ...]] = []

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        recorded_calls.append(args[1:])
        return _proc(returncode=0, stdout=b"")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        # clone_root.exists() returns False on first call (triggering clone), then True
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text"),
    ):
        await store.upload("some/file.md", "data")

    # The very first command must be "clone"
    first_subcommand = recorded_calls[0][0]
    assert first_subcommand == "clone"


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_runs_fetch_then_show() -> None:
    store = _make_store()
    file_content = b"spec content here"

    call_idx = 0

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        nonlocal call_idx
        call_idx += 1
        sub_args = args[1:]
        is_show = "show" in sub_args
        stdout = file_content if is_show else b""
        return _proc(returncode=0, stdout=stdout)

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
    ):
        result = await store.download("artifacts/feat-x/spec.r1.md")

    assert result == "spec content here"
    # Two git calls: fetch + show
    assert call_idx == 2


@pytest.mark.asyncio
async def test_download_returns_decoded_utf8() -> None:
    store = _make_store()
    content = "héllo wörld"

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        sub_args = args[1:]
        is_show = "show" in sub_args
        return _proc(returncode=0, stdout=content.encode("utf-8") if is_show else b"")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
    ):
        result = await store.download("some/path.md")

    assert result == content


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exists_returns_true_when_path_in_ls_tree() -> None:
    store = _make_store()
    target = "artifacts/feat-x/spec.r1.md"
    ls_tree_output = f"artifacts/feat-x/brief.md\n{target}\nartifacts/feat-x/state.json\n"

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        sub_args = args[1:]
        is_ls_tree = "ls-tree" in sub_args
        return _proc(returncode=0, stdout=ls_tree_output.encode() if is_ls_tree else b"")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
    ):
        result = await store.exists(target)

    assert result is True


@pytest.mark.asyncio
async def test_exists_returns_false_when_path_not_in_ls_tree() -> None:
    store = _make_store()
    ls_tree_output = "artifacts/feat-x/brief.md\n"

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        sub_args = args[1:]
        is_ls_tree = "ls-tree" in sub_args
        return _proc(returncode=0, stdout=ls_tree_output.encode() if is_ls_tree else b"")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
    ):
        result = await store.exists("artifacts/feat-x/missing.md")

    assert result is False


@pytest.mark.asyncio
async def test_exists_returns_false_when_git_command_fails() -> None:
    store = _make_store()

    async def fake_create_subprocess(*args: str, **kwargs: object) -> MagicMock:
        return _proc(returncode=128, stdout=b"", stderr=b"fatal: unknown branch")

    with (
        patch("agentharness.github_artifacts.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess),
        patch.object(Path, "exists", return_value=True),
    ):
        result = await store.exists("any/path.md")

    assert result is False


# ---------------------------------------------------------------------------
# _checkout_or_create — three-tier fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_or_create_uses_existing_local_branch() -> None:
    """First git checkout succeeds — no fallback needed."""
    store = _make_store()
    branch = "feat-login-form"

    run_git_calls: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        run_git_calls.append(args)
        return b""

    with patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git):
        await store._checkout_or_create(branch)

    # Only one checkout call should have been made
    assert len(run_git_calls) == 1
    assert "checkout" in run_git_calls[0]
    assert branch in run_git_calls[0]
    # Must NOT include "-b" (not creating a new branch)
    assert "-b" not in run_git_calls[0]


@pytest.mark.asyncio
async def test_checkout_or_create_falls_back_to_remote_tracking_branch() -> None:
    """First checkout fails → creates local tracking branch from remote."""
    store = _make_store()
    branch = "epic-auth-rewrite"

    call_count = 0

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        nonlocal call_count
        call_count += 1
        # First call (plain checkout) fails; subsequent calls succeed
        if call_count == 1:
            raise RuntimeError(f"git checkout {branch} failed (exit 1): pathspec not found")
        return b""

    with patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git):
        await store._checkout_or_create(branch)

    assert call_count == 2


@pytest.mark.asyncio
async def test_checkout_or_create_creates_fresh_branch_when_no_remote() -> None:
    """Both first and second tiers fail → creates a fresh local branch."""
    store = _make_store()
    branch = "feat-brand-new"

    call_count = 0

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        nonlocal call_count
        call_count += 1
        # First two calls fail; third (fresh branch) succeeds
        if call_count <= 2:
            raise RuntimeError(f"git failed (exit 1): not found")
        return b""

    with patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git):
        await store._checkout_or_create(branch)

    assert call_count == 3
    # Third call must use "-b" without a remote ref
    # (We can't inspect args directly here, but 3 calls means all 3 tiers ran)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_noop() -> None:
    store = _make_store()
    await store.close()  # Must not raise.


# ---------------------------------------------------------------------------
# sync_working_branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_working_branch_fetches_then_merges_feature_and_base() -> None:
    """Happy path: fetch → checkout feature → ff-merge feature → merge default branch."""
    store = _make_store()

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        # Return default branch ref for symbolic-ref call
        if "symbolic-ref" in args:
            return b"origin/main\n"
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()

    subcommands = [a for a in (args[2] if len(args) > 2 else args[0] for args in recorded) if a in ("fetch", "checkout", "merge", "symbolic-ref")]
    assert "fetch" in subcommands
    assert "checkout" in subcommands
    assert "merge" in subcommands

    # Verify merge of default branch with -X ours
    merge_calls = [args for args in recorded if "merge" in args]
    ours_merges = [args for args in merge_calls if "-X" in args and "ours" in args]
    assert any("origin/main" in args for args in ours_merges)


@pytest.mark.asyncio
async def test_sync_working_branch_returns_early_on_fetch_failure() -> None:
    """If fetch fails, sync bails out gracefully without raising."""
    store = _make_store()

    call_count = 0

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        nonlocal call_count
        call_count += 1
        if "fetch" in args:
            raise RuntimeError("network error")
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()  # Must not raise

    # Only one call (fetch) should have been made before early return
    assert call_count == 1


@pytest.mark.asyncio
async def test_sync_working_branch_falls_back_to_ours_when_ff_fails() -> None:
    """When fast-forward merge fails, retries with -X ours strategy."""
    store = _make_store()

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        if "symbolic-ref" in args:
            return b"origin/main\n"
        # Fail the ff-only merge, succeed on -X ours and everything else
        if "--ff-only" in args:
            raise RuntimeError("not a fast-forward")
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()

    # Should have attempted -X ours for the feature branch
    ours_feature_merges = [
        args for args in recorded
        if "merge" in args and "-X" in args and "ours" in args and f"origin/{_FEATURE_ID}" in args
    ]
    assert ours_feature_merges


@pytest.mark.asyncio
async def test_sync_working_branch_skips_base_merge_when_no_default_branch() -> None:
    """When symbolic-ref fails to resolve origin/HEAD, base branch merge is skipped."""
    store = _make_store()

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        if "symbolic-ref" in args:
            raise RuntimeError("ref not found")
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()

    # Only feature-branch merges should have happened (no base branch merge)
    base_merges = [
        args for args in recorded
        if "merge" in args and "-X" in args and "ours" in args and "origin/main" in args
    ]
    assert not base_merges


@pytest.mark.asyncio
async def test_sync_working_branch_aborts_when_base_merge_fails() -> None:
    """When base branch merge fails, merge --abort is called to restore clean state."""
    store = _make_store()

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        if "symbolic-ref" in args:
            return b"origin/main\n"
        # Fail when merging origin/main
        if "merge" in args and "origin/main" in args:
            raise RuntimeError("merge conflict")
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()  # Must not raise

    abort_calls = [args for args in recorded if "merge" in args and "--abort" in args]
    assert abort_calls


# ---------------------------------------------------------------------------
# sync_working_branch — base_branch override (epic children)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_working_branch_uses_base_branch_instead_of_default_when_set() -> None:
    """When base_branch is set, sync merges from base_branch, not origin/HEAD default."""
    store = GitHubArtifactStore(
        owner=_OWNER,
        repo=_REPO,
        feature_id=_FEATURE_ID,
        clone_dir=_CLONE_DIR,
        base_branch="epic-my-epic",
    )

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()

    # Must merge from the epic branch
    epic_merges = [
        args for args in recorded
        if "merge" in args and "origin/epic-my-epic" in args
    ]
    assert epic_merges, "Expected merge from epic branch"

    # Must NOT call symbolic-ref (no need to detect default branch)
    symbolic_ref_calls = [args for args in recorded if "symbolic-ref" in args]
    assert not symbolic_ref_calls

    # Must NOT merge from main
    main_merges = [args for args in recorded if "merge" in args and "origin/main" in args]
    assert not main_merges


@pytest.mark.asyncio
async def test_sync_working_branch_without_base_branch_merges_default() -> None:
    """Without base_branch, sync behaviour is unchanged — merges from origin/HEAD default."""
    store = _make_store()  # no base_branch

    recorded: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> bytes:
        recorded.append(args)
        if "symbolic-ref" in args:
            return b"origin/main\n"
        return b""

    with (
        patch("agentharness.github_artifacts._run_git", side_effect=fake_run_git),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir"),
    ):
        await store.sync_working_branch()

    main_merges = [args for args in recorded if "merge" in args and "origin/main" in args]
    assert main_merges


def test_from_config_passes_base_branch() -> None:
    """from_config forwards base_branch to the store."""
    config = MagicMock()
    config.github.owner = "org"
    config.github.runs_repo = "runs"
    config.github.clone_dir = ".worktrees"

    store = GitHubArtifactStore.from_config(config, "feat-child", base_branch="epic-parent")

    assert store._base_branch == "epic-parent"
