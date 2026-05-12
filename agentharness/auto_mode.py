"""Runtime toggle for observer auto-mode via sentinel file."""
from __future__ import annotations

from pathlib import Path

TOGGLE_PATH = Path("logs/auto-mode.enabled")


def is_enabled() -> bool:
    return TOGGLE_PATH.exists()


def enable() -> None:
    TOGGLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOGGLE_PATH.touch(exist_ok=True)


def disable() -> None:
    TOGGLE_PATH.unlink(missing_ok=True)


def toggle() -> bool:
    """Flip current state. Returns the new state (True = enabled)."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
