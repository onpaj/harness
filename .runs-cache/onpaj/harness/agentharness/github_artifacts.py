"""Git feature-branch implementation of ArtifactStorage."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agentharness.config import Config

# Number of bytes beyond which content is treated as binary for writing
_BINARY_THRESHOLD = 0


async def _run_git(*args: str, cwd: Path | None = None) -> bytes:
    """Run a git command, returning stdout. Raise RuntimeError on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()}"
        )
    return stdout


class GitHubArtifactStore:
    """Artifact store backed by a git feature branch in a GitHub repository.

    Files are committed directly to the feature branch.  A local clone of the
    runs repo is kept in ``clone_dir/owner/repo`` and used as a write-through
    cache so that all git operations remain local (followed by a push).
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        feature_id: str,
        clone_dir: Path,
    ) -> None:
        self._owner = owner
        self._repo = repo
        self._feature_id = feature_id
        self._clone_dir = clone_dir
        self._clone_root = clone_dir / owner / repo

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: Config, feature_id: str) -> GitHubArtifactStore:
        owner = config.github.owner
        repo = config.github.runs_repo
        clone_dir = Path(config.github.clone_dir)
        return cls(owner=owner, repo=repo, feature_id=feature_id, clone_dir=clone_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_clone(self) -> None:
        """Clone the repo if the local clone root does not exist."""
        if self._clone_root.exists():
            return
        self._clone_root.parent.mkdir(parents=True, exist_ok=True)
        token = os.environ.get("GITHUB_TOKEN", "")
        clone_url = f"https://{token}@github.com/{self._owner}/{self._repo}.git"
        await _run_git("clone", clone_url, str(self._clone_root))

    # ------------------------------------------------------------------
    # ArtifactStorage protocol
    # ------------------------------------------------------------------

    async def upload(self, path: str, content: str | bytes) -> None:
        """Write *content* to *path* on the feature branch and push."""
        await self._ensure_clone()

        # Bring remote refs up to date; tolerate a branch that doesn't exist
        # remotely yet (fetch may fail on first push for a brand-new branch).
        try:
            await _run_git(
                "-C", str(self._clone_root),
                "fetch", "origin", self._feature_id,
            )
        except RuntimeError:
            # Branch may not exist on remote yet; proceed.
            pass

        await _run_git(
            "-C", str(self._clone_root),
            "checkout", self._feature_id,
        )

        # Write the file into the working tree.
        dest = self._clone_root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            dest.write_text(content, encoding="utf-8")
        else:
            dest.write_bytes(content)

        await _run_git("-C", str(self._clone_root), "add", path)

        # Commit only if there is something staged (nothing-to-commit is OK).
        try:
            await _run_git(
                "-C", str(self._clone_root),
                "commit", "-m", f"agent: upload {path}",
            )
        except RuntimeError as exc:
            if "nothing to commit" not in str(exc).lower():
                raise

        await _run_git(
            "-C", str(self._clone_root),
            "push", "origin", self._feature_id,
        )

    async def download(self, path: str) -> str:
        """Return the UTF-8 contents of *path* from the remote feature branch."""
        await self._ensure_clone()

        await _run_git(
            "-C", str(self._clone_root),
            "fetch", "origin", self._feature_id,
        )
        stdout = await _run_git(
            "-C", str(self._clone_root),
            "show", f"origin/{self._feature_id}:{path}",
        )
        return stdout.decode("utf-8")

    async def exists(self, path: str) -> bool:
        """Return True if *path* exists on the remote feature branch."""
        await self._ensure_clone()

        try:
            await _run_git(
                "-C", str(self._clone_root),
                "fetch", "origin", self._feature_id,
            )
            stdout = await _run_git(
                "-C", str(self._clone_root),
                "ls-tree", "-r", f"origin/{self._feature_id}", "--name-only",
            )
        except RuntimeError:
            return False

        listed_paths = stdout.decode("utf-8").splitlines()
        return path in listed_paths

    async def close(self) -> None:
        """No-op; git subprocesses are short-lived."""

    # ------------------------------------------------------------------
    # Extra helper (used by run_task.py for developer agent work dir)
    # ------------------------------------------------------------------

    def get_work_dir(self) -> Path:
        """Return the local directory where developer agents write code."""
        return self._clone_root / "implementation"
