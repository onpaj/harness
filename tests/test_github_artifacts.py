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
_CLONE_DIR = Path("/tmp/runs-cache-test")
_CLONE_ROOT = _CLONE_DIR / _OWNER / _REPO


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
    config.github.clone_dir = ".runs-cache"

    store = GitHubArtifactStore.from_config(config, "feat-xyz")

    assert store._owner == "org"
    assert store._repo == "runs"
    assert store._feature_id == "feat-xyz"
    assert store._clone_dir == Path(".runs-cache")
    assert store._clone_root == Path(".runs-cache") / "org" / "runs"


# ---------------------------------------------------------------------------
# get_work_dir
# ---------------------------------------------------------------------------


def test_get_work_dir_returns_implementation_subdir() -> None:
    store = _make_store()
    expected = _CLONE_ROOT / "artifacts" / _FEATURE_ID
    assert store.get_work_dir() == expected


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
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_noop() -> None:
    store = _make_store()
    await store.close()  # Must not raise.
