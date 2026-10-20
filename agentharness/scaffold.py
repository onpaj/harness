"""Install packaged scaffolding into a consumer repo without clobbering local edits.

`agentharness init` used to overwrite every scaffolding file unconditionally,
so a consumer repo that fixed a skill locally (and committed the fix) lost it
on the next `init` -- including the one a cloud session's setup script runs at
the start of every run.

Each file `init` installs is now recorded, by content hash, in a manifest
committed alongside it. On the next `init` a destination file is:

  * written       if it is missing, or still byte-identical to what the
                  manifest says `init` installed last time (i.e. untouched),
  * left alone    if it differs from that recorded hash (a local edit),
  * written       if the manifest has no record of it (first run on a repo
                  that predates the manifest -- there is no way to tell an
                  edit from an old release, so the packaged version wins).

`overwrite_local=True` restores the old behaviour for a deliberate reset.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = ".agentharness-manifest.json"


@dataclass(frozen=True)
class CopyResult:
    """Outcome of installing one directory: new manifest entries and what was skipped."""

    recorded: dict[str, str]
    written: tuple[str, ...]
    kept: tuple[str, ...]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(target: Path) -> dict[str, str]:
    """Return the recorded {relative path: sha256}; empty if absent or unreadable."""
    path = target / MANIFEST_NAME
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {str(k): str(v) for k, v in files.items() if isinstance(v, str)}


def save_manifest(target: Path, files: dict[str, str]) -> None:
    payload = {"version": 1, "files": dict(sorted(files.items()))}
    (target / MANIFEST_NAME).write_text(json.dumps(payload, indent=2) + "\n")


def _is_locally_modified(dst_file: Path, recorded_hash: str | None) -> bool:
    if recorded_hash is None or not dst_file.exists():
        return False
    return file_hash(dst_file) != recorded_hash


def copy_dir(
    src: Path,
    dst: Path,
    target: Path,
    manifest: dict[str, str],
    overwrite_local: bool = False,
) -> CopyResult:
    """Install the regular files of `src` into `dst`, honouring local edits."""
    if not src.exists():
        return CopyResult({}, (), ())
    dst.mkdir(parents=True, exist_ok=True)

    recorded: dict[str, str] = {}
    written: list[str] = []
    kept: list[str] = []
    for src_file in sorted(src.iterdir()):
        if not src_file.is_file():
            continue
        dst_file = dst / src_file.name
        rel = dst_file.relative_to(target).as_posix()
        previous = manifest.get(rel)
        if not overwrite_local and _is_locally_modified(dst_file, previous):
            # Keep the old record so the file is still seen as modified next time.
            recorded[rel] = previous  # type: ignore[assignment]
            kept.append(rel)
            continue
        shutil.copy2(src_file, dst_file)
        recorded[rel] = file_hash(dst_file)
        written.append(rel)
    return CopyResult(recorded, tuple(written), tuple(kept))
