"""Pure subprocess boundary for git worktree operations."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VALID_FEATURE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_GITIGNORE_ENTRY = ".worktrees/"


class WorktreeError(Exception):
    """Base class for worktree errors."""


class WorktreeCreationError(WorktreeError):
    """Raised when git worktree add fails."""

    def __init__(self, message: str, command: list[str] | None = None, stderr: str = "", returncode: int | None = None):
        super().__init__(message)
        self.command = command
        self.stderr = stderr
        self.returncode = returncode


class WorktreeRemovalError(WorktreeError):
    """Raised on unrecoverable git worktree remove failure."""

    def __init__(self, message: str, command: list[str] | None = None, stderr: str = "", returncode: int | None = None):
        super().__init__(message)
        self.command = command
        self.stderr = stderr
        self.returncode = returncode


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ensure_gitignore_entry(repo_root: Path) -> None:
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if _GITIGNORE_ENTRY in content.splitlines():
            return
        updated = content.rstrip("\n") + "\n" + _GITIGNORE_ENTRY + "\n"
        gitignore.write_text(updated)
    else:
        gitignore.write_text(_GITIGNORE_ENTRY + "\n")


def _find_repo_root() -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"], timeout=10)
    if result.returncode != 0:
        raise WorktreeCreationError(
            "Not inside a git repository",
            command=["git", "rev-parse", "--show-toplevel"],
            stderr=result.stderr,
            returncode=result.returncode,
        )
    return Path(result.stdout.strip())


def create_worktree(
    feature_id: str,
    base_branch: Optional[str],
    base_dir: str = ".worktrees",
    timeout: int = 30,
) -> str:
    """
    Create a git worktree for the given feature_id.

    Returns the absolute path to the created worktree.
    Raises WorktreeCreationError on any failure.
    """
    if not VALID_FEATURE_ID_RE.match(feature_id):
        raise WorktreeCreationError(
            f"Invalid feature_id {feature_id!r}: must match [a-zA-Z0-9_-]{{1,64}}"
        )

    repo_root = _find_repo_root()
    worktree_path = (repo_root / base_dir / feature_id).resolve()
    branch_name = f"feature/{feature_id}"
    ref = base_branch or "HEAD"

    cmd = ["git", "worktree", "add", str(worktree_path), "-b", branch_name, ref]

    logger.info(
        "Worktree creation started",
        extra={"feature_id": feature_id, "target_path": str(worktree_path), "base_branch": ref},
    )
    start = time.monotonic()

    try:
        result = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WorktreeCreationError(
            f"git worktree add timed out after {timeout}s for feature {feature_id!r}",
            command=cmd,
            stderr="",
            returncode=None,
        )

    if result.returncode != 0:
        logger.error(
            "git worktree add failed",
            extra={
                "feature_id": feature_id,
                "worktree_path": str(worktree_path),
                "command": cmd,
                "returncode": result.returncode,
                "stderr": result.stderr,
            },
        )
        raise WorktreeCreationError(
            f"git worktree add failed for feature {feature_id!r}: {result.stderr.strip()}",
            command=cmd,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    _ensure_gitignore_entry(repo_root)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Worktree creation succeeded",
        extra={"feature_id": feature_id, "worktree_path": str(worktree_path), "elapsed_ms": elapsed_ms},
    )

    return str(worktree_path)


def remove_worktree(worktree_path: str, timeout: int = 15) -> None:
    """
    Remove a git worktree. Idempotent: logs WARNING if already gone.

    Tries safe removal first; falls back to --force once on clean-state failure.
    Raises WorktreeRemovalError only on unrecoverable failure.
    """
    if not Path(worktree_path).exists():
        logger.warning(
            "Worktree path already gone, skipping removal",
            extra={"worktree_path": worktree_path},
        )
        return

    logger.info("Worktree removal started", extra={"worktree_path": worktree_path})
    start = time.monotonic()

    safe_cmd = ["git", "worktree", "remove", worktree_path]
    try:
        result = _run(safe_cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WorktreeRemovalError(
            f"git worktree remove timed out after {timeout}s for {worktree_path!r}",
            command=safe_cmd,
            stderr="",
            returncode=None,
        )

    if result.returncode == 0:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Worktree removal succeeded",
            extra={"worktree_path": worktree_path, "elapsed_ms": elapsed_ms},
        )
        return

    force_cmd = ["git", "worktree", "remove", "--force", worktree_path]
    try:
        force_result = _run(force_cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WorktreeRemovalError(
            f"git worktree remove --force timed out after {timeout}s for {worktree_path!r}",
            command=force_cmd,
            stderr="",
            returncode=None,
        )

    if force_result.returncode != 0:
        logger.error(
            "git worktree remove failed",
            extra={
                "worktree_path": worktree_path,
                "command": force_cmd,
                "returncode": force_result.returncode,
                "stderr": force_result.stderr,
            },
        )
        raise WorktreeRemovalError(
            f"git worktree remove --force failed for {worktree_path!r}: {force_result.stderr.strip()}",
            command=force_cmd,
            stderr=force_result.stderr,
            returncode=force_result.returncode,
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Worktree removal succeeded",
        extra={"worktree_path": worktree_path, "elapsed_ms": elapsed_ms},
    )


def is_worktree_valid(worktree_path: str) -> bool:
    """Return True if worktree_path is a registered git worktree."""
    result = _run(["git", "worktree", "list", "--porcelain"], timeout=10)
    if result.returncode != 0:
        return False
    resolved = str(Path(worktree_path).resolve())
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            registered = line[len("worktree "):].strip()
            if Path(registered).resolve() == Path(resolved).resolve():
                return True
    return False
