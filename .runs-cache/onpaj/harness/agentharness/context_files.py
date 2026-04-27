"""Resolve and inject per-agent context files into prompts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)

_SIZE_WARNING_BYTES = 51_200


@dataclass(frozen=True)
class ResolvedContextFile:
    declared_path: str
    resolved_path: Path
    display_path: str
    content: str
    size_bytes: int


@dataclass(frozen=True)
class ContextFileResult:
    agent_name: str
    files: tuple[ResolvedContextFile, ...]
    warnings: tuple[str, ...]
    total_bytes: int


def resolve_context_files(
    declared_paths: list[str],
    agent_name: str,
    config_dir: Path,
) -> ContextFileResult:
    """Resolve declared paths to files and read their contents."""
    files: list[ResolvedContextFile] = []
    warnings: list[str] = []

    for declared in declared_paths:
        expanded = _expand_path(declared, config_dir)
        if not expanded:
            _logger.debug("Context directory is empty: %s (agent: %s)", declared, agent_name)

        for resolved_path, display_path in expanded:
            _logger.debug("Resolved context file: %s", resolved_path)
            content = _read_file(resolved_path, declared, agent_name)
            if content is None:
                warnings.append(f"Skipped unreadable file: {resolved_path}")
                continue
            files.append(
                ResolvedContextFile(
                    declared_path=declared,
                    resolved_path=resolved_path,
                    display_path=display_path,
                    content=content,
                    size_bytes=len(content.encode("utf-8")),
                )
            )

    total_bytes = sum(f.size_bytes for f in files)

    if files:
        _logger.info(
            "Loaded %d context file(s) for agent '%s' (%d bytes)",
            len(files),
            agent_name,
            total_bytes,
        )

    if total_bytes > _SIZE_WARNING_BYTES:
        _logger.warning(
            "Context files for agent '%s' total %d bytes — exceeding 50 KB may cause "
            "prompt truncation or excessive token cost",
            agent_name,
            total_bytes,
        )

    return ContextFileResult(
        agent_name=agent_name,
        files=tuple(files),
        warnings=tuple(warnings),
        total_bytes=total_bytes,
    )


def format_context_section(files: tuple[ResolvedContextFile, ...]) -> str:
    """Format resolved files into the prompt injection string."""
    if not files:
        return ""

    blocks = "\n\n".join(
        f"### Context: {f.display_path}\n\n{f.content}" for f in files
    )
    return f"## Agent Context Files\n\n{blocks}"


def _expand_path(declared_path: str, config_dir: Path) -> list[tuple[Path, str]]:
    """Expand a declared path to (resolved_path, display_path) tuples.

    Supports:
    - ``~`` home directory prefix (e.g. ``~/.claude/...``)
    - Glob wildcards anywhere in the path (e.g. ``**/skills/*/SKILL.md``)
    - Trailing ``/**`` for recursive directory expansion
    - Absolute and config-dir-relative paths
    """
    expanded = declared_path
    if expanded.startswith("~"):
        expanded = str(Path(expanded).expanduser())

    is_recursive = expanded.endswith("/**")
    has_glob = "*" in expanded or "?" in expanded or "[" in expanded

    if is_recursive:
        raw = expanded[:-3]
        base = Path(raw) if Path(raw).is_absolute() else config_dir / raw
        if not base.exists():
            _logger.warning("Context file not found: %s", declared_path)
            return []
        files = sorted(
            (p for p in base.rglob("*") if p.is_file()),
            key=lambda p: str(p),
        )
        return [(f, str(f)) for f in files]

    if has_glob:
        if Path(expanded).is_absolute():
            parts = Path(expanded).parts
            # Find the first part containing a wildcard to split root from pattern
            split = next((i for i, p in enumerate(parts) if "*" in p or "?" in p or "[" in p), 1)
            root = Path(*parts[:split])
            pattern = str(Path(*parts[split:]))
        else:
            root = config_dir
            pattern = expanded
        matches = sorted(
            (p for p in root.glob(pattern) if p.is_file()),
            key=lambda p: str(p),
        )
        if not matches:
            _logger.warning("Context glob matched no files: %s", declared_path)
        return [(f, str(f)) for f in matches]

    base = Path(expanded) if Path(expanded).is_absolute() else config_dir / expanded

    if not base.exists():
        _logger.warning("Context file not found: %s", declared_path)
        return []

    if base.is_dir():
        files = sorted(
            (p for p in base.iterdir() if p.is_file()),
            key=lambda p: str(p),
        )
        return [(f, str(f)) for f in files]

    return [(base, declared_path)]


def _read_file(resolved_path: Path, declared: str, agent_name: str) -> str | None:
    """Read a file as UTF-8. Returns content or None on failure."""
    try:
        return resolved_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _logger.warning("Context file not found: %s (agent: %s)", declared, agent_name)
        return None
    except PermissionError as exc:
        _logger.warning(
            "Context file unreadable: %s (agent: %s): %s", declared, agent_name, exc
        )
        return None
    except UnicodeDecodeError:
        _logger.warning(
            "Context file not valid UTF-8: %s (agent: %s)", declared, agent_name
        )
        return None
