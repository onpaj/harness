"""Tests for worktree_manager.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from agentharness.worktree_manager import (
    VALID_FEATURE_ID_RE,
    WorktreeCreationError,
    WorktreeRemovalError,
    create_worktree,
    is_worktree_valid,
    remove_worktree,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = "/repo"
BASE_DIR = ".worktrees"


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _mock_run_side_effect(*responses):
    """Return a side_effect function that yields successive CompletedProcess responses."""
    iter_ = iter(responses)

    def side_effect(cmd, **kwargs):
        return next(iter_)

    return side_effect


# ---------------------------------------------------------------------------
# VALID_FEATURE_ID_RE
# ---------------------------------------------------------------------------


class TestValidFeatureIdRegex:
    @pytest.mark.parametrize("fid", ["feat-abc", "feat123", "a", "A-z_0", "x" * 64])
    def test_valid_ids_match(self, fid):
        assert VALID_FEATURE_ID_RE.match(fid)

    @pytest.mark.parametrize("fid", ["../evil", "", "x" * 65, "feat/slash", "feat space", "feat.dot"])
    def test_invalid_ids_do_not_match(self, fid):
        assert not VALID_FEATURE_ID_RE.match(fid)


# ---------------------------------------------------------------------------
# create_worktree unit tests
# ---------------------------------------------------------------------------


class TestCreateWorktree:
    def _patch_run(self, responses):
        return patch(
            "agentharness.worktree_manager._run",
            side_effect=_mock_run_side_effect(*responses),
        )

    def _patch_repo_root(self, path: str = REPO_ROOT):
        return patch(
            "agentharness.worktree_manager._find_repo_root",
            return_value=Path(path),
        )

    def _patch_gitignore(self):
        return patch("agentharness.worktree_manager._ensure_gitignore_entry")

    def test_invalid_feature_id_raises_creation_error(self):
        with pytest.raises(WorktreeCreationError, match="Invalid feature_id"):
            create_worktree("../evil", base_branch=None)

    def test_empty_feature_id_raises_creation_error(self):
        with pytest.raises(WorktreeCreationError, match="Invalid feature_id"):
            create_worktree("", base_branch=None)

    def test_too_long_feature_id_raises_creation_error(self):
        with pytest.raises(WorktreeCreationError, match="Invalid feature_id"):
            create_worktree("x" * 65, base_branch=None)

    def test_special_chars_in_feature_id_raises_creation_error(self):
        with pytest.raises(WorktreeCreationError, match="Invalid feature_id"):
            create_worktree("feat/name", base_branch=None)

    def test_successful_creation_returns_absolute_path(self, tmp_path):
        feature_id = "feat-abc"
        with self._patch_repo_root(str(tmp_path)), self._patch_gitignore():
            with patch(
                "agentharness.worktree_manager._run",
                return_value=_make_completed(returncode=0),
            ):
                result = create_worktree(feature_id, base_branch=None, base_dir=".worktrees")

        expected = str((tmp_path / ".worktrees" / feature_id).resolve())
        assert result == expected

    def test_uses_base_branch_when_provided(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)), self._patch_gitignore():
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()) as mock_run:
                create_worktree("feat-abc", base_branch="main")

        cmd = mock_run.call_args[0][0]
        assert "main" in cmd

    def test_falls_back_to_HEAD_when_base_branch_is_none(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)), self._patch_gitignore():
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()) as mock_run:
                create_worktree("feat-abc", base_branch=None)

        cmd = mock_run.call_args[0][0]
        assert "HEAD" in cmd

    def test_branch_name_is_feature_slash_id(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)), self._patch_gitignore():
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()) as mock_run:
                create_worktree("my-feat", base_branch=None)

        cmd = mock_run.call_args[0][0]
        assert "feature/my-feat" in cmd

    def test_nonzero_returncode_raises_creation_error(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)):
            with patch(
                "agentharness.worktree_manager._run",
                return_value=_make_completed(returncode=128, stderr="fatal: branch already exists"),
            ):
                with pytest.raises(WorktreeCreationError) as exc_info:
                    create_worktree("feat-abc", base_branch=None)

        err = exc_info.value
        assert err.returncode == 128
        assert "already exists" in err.stderr

    def test_branch_collision_captured_in_error(self, tmp_path):
        stderr = "fatal: A branch named 'feature/feat-abc' already exists."
        with self._patch_repo_root(str(tmp_path)):
            with patch(
                "agentharness.worktree_manager._run",
                return_value=_make_completed(returncode=128, stderr=stderr),
            ):
                with pytest.raises(WorktreeCreationError) as exc_info:
                    create_worktree("feat-abc", base_branch=None)

        assert exc_info.value.stderr == stderr

    def test_timeout_raises_creation_error(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)):
            with patch(
                "agentharness.worktree_manager._run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ):
                with pytest.raises(WorktreeCreationError, match="timed out"):
                    create_worktree("feat-abc", base_branch=None)

    def test_gitignore_entry_appended_on_success(self, tmp_path):
        with self._patch_repo_root(str(tmp_path)):
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()):
                create_worktree("feat-abc", base_branch=None)

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".worktrees/" in gitignore.read_text()

    def test_gitignore_entry_not_duplicated(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".worktrees/\n")

        with self._patch_repo_root(str(tmp_path)):
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()):
                create_worktree("feat-abc", base_branch=None)

        content = gitignore.read_text()
        assert content.count(".worktrees/") == 1

    def test_list_form_args_no_shell(self, tmp_path):
        """Verify _run is called with a list (not a string) so shell=False is effective."""
        with self._patch_repo_root(str(tmp_path)), self._patch_gitignore():
            with patch("agentharness.worktree_manager._run", return_value=_make_completed()) as mock_run:
                create_worktree("feat-abc", base_branch=None)

        cmd = mock_run.call_args[0][0]
        assert isinstance(cmd, list)
        assert cmd[0] == "git"


# ---------------------------------------------------------------------------
# remove_worktree unit tests
# ---------------------------------------------------------------------------


class TestRemoveWorktree:
    def test_idempotent_already_gone_logs_warning(self, tmp_path, caplog):
        absent_path = str(tmp_path / "gone")
        with patch("agentharness.worktree_manager._run") as mock_run:
            remove_worktree(absent_path)

        mock_run.assert_not_called()

    def test_safe_removal_succeeds(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        with patch(
            "agentharness.worktree_manager._run",
            return_value=_make_completed(returncode=0),
        ) as mock_run:
            remove_worktree(str(worktree))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--force" not in cmd

    def test_force_fallback_on_safe_failure(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        responses = [
            _make_completed(returncode=1, stderr="contains modified or untracked files"),
            _make_completed(returncode=0),
        ]
        with patch(
            "agentharness.worktree_manager._run",
            side_effect=_mock_run_side_effect(*responses),
        ) as mock_run:
            remove_worktree(str(worktree))

        assert mock_run.call_count == 2
        force_cmd = mock_run.call_args_list[1][0][0]
        assert "--force" in force_cmd

    def test_unrecoverable_failure_raises_removal_error(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        responses = [
            _make_completed(returncode=1, stderr="error: first"),
            _make_completed(returncode=1, stderr="error: force also failed"),
        ]
        with patch(
            "agentharness.worktree_manager._run",
            side_effect=_mock_run_side_effect(*responses),
        ):
            with pytest.raises(WorktreeRemovalError) as exc_info:
                remove_worktree(str(worktree))

        assert exc_info.value.returncode == 1

    def test_timeout_raises_removal_error(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        with patch(
            "agentharness.worktree_manager._run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
        ):
            with pytest.raises(WorktreeRemovalError, match="timed out"):
                remove_worktree(str(worktree))


# ---------------------------------------------------------------------------
# is_worktree_valid unit tests
# ---------------------------------------------------------------------------


class TestIsWorktreeValid:
    def _porcelain_output(self, *paths: str) -> str:
        lines = []
        for p in paths:
            lines.append(f"worktree {p}")
            lines.append("HEAD abc123")
            lines.append("branch refs/heads/main")
            lines.append("")
        return "\n".join(lines)

    def test_returns_true_when_path_in_list(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        output = self._porcelain_output(str(wt))
        with patch("agentharness.worktree_manager._run", return_value=_make_completed(stdout=output)):
            assert is_worktree_valid(str(wt)) is True

    def test_returns_false_when_path_not_in_list(self, tmp_path):
        output = self._porcelain_output("/other/path")
        with patch("agentharness.worktree_manager._run", return_value=_make_completed(stdout=output)):
            assert is_worktree_valid(str(tmp_path / "missing")) is False

    def test_returns_false_on_git_failure(self):
        with patch("agentharness.worktree_manager._run", return_value=_make_completed(returncode=128)):
            assert is_worktree_valid("/some/path") is False


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestWorktreeIntegration:
    """Real git operations against a temp repo."""

    @pytest.fixture()
    def git_repo(self, tmp_path):
        """Initialize a bare-enough git repo for worktree tests."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
        # Need at least one commit for worktree add to work
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
        return tmp_path

    def test_create_and_remove_real_worktree(self, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo)

        feature_id = "test-feat-123"
        path = create_worktree(feature_id, base_branch=None, base_dir=".worktrees")

        assert Path(path).is_dir()
        assert is_worktree_valid(path)

        remove_worktree(path)

        assert not Path(path).exists()
