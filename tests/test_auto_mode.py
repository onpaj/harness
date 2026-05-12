"""Unit tests for auto_mode toggle module."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentharness.auto_mode as auto_mode_module


@pytest.fixture(autouse=True)
def isolated_toggle_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    toggle = tmp_path / "logs" / "auto-mode.enabled"
    monkeypatch.setattr(auto_mode_module, "TOGGLE_PATH", toggle)
    return toggle


class TestIsEnabled:
    def test_false_when_file_absent(self):
        assert auto_mode_module.is_enabled() is False

    def test_true_when_file_present(self, isolated_toggle_path: Path):
        isolated_toggle_path.parent.mkdir(parents=True, exist_ok=True)
        isolated_toggle_path.touch()
        assert auto_mode_module.is_enabled() is True


class TestEnable:
    def test_creates_file(self, isolated_toggle_path: Path):
        auto_mode_module.enable()
        assert isolated_toggle_path.exists()

    def test_creates_parent_dirs(self, isolated_toggle_path: Path):
        assert not isolated_toggle_path.parent.exists()
        auto_mode_module.enable()
        assert isolated_toggle_path.parent.exists()

    def test_idempotent(self, isolated_toggle_path: Path):
        auto_mode_module.enable()
        auto_mode_module.enable()
        assert isolated_toggle_path.exists()


class TestDisable:
    def test_removes_file(self, isolated_toggle_path: Path):
        isolated_toggle_path.parent.mkdir(parents=True, exist_ok=True)
        isolated_toggle_path.touch()
        auto_mode_module.disable()
        assert not isolated_toggle_path.exists()

    def test_no_error_when_file_absent(self):
        auto_mode_module.disable()  # must not raise

    def test_idempotent(self, isolated_toggle_path: Path):
        auto_mode_module.disable()
        auto_mode_module.disable()


class TestToggle:
    def test_enables_when_off(self, isolated_toggle_path: Path):
        result = auto_mode_module.toggle()
        assert result is True
        assert isolated_toggle_path.exists()

    def test_disables_when_on(self, isolated_toggle_path: Path):
        auto_mode_module.enable()
        result = auto_mode_module.toggle()
        assert result is False
        assert not isolated_toggle_path.exists()

    def test_returns_new_state(self, isolated_toggle_path: Path):
        first = auto_mode_module.toggle()
        second = auto_mode_module.toggle()
        assert first is True
        assert second is False
