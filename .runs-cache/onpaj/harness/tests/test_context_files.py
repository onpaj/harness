"""Unit tests for context_files module."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agentharness.context_files import (
    ContextFileResult,
    ResolvedContextFile,
    _expand_path,
    _read_file,
    format_context_section,
    resolve_context_files,
)

FIXTURES = Path(__file__).parent / "fixtures" / "context_files"


# ---------------------------------------------------------------------------
# _expand_path
# ---------------------------------------------------------------------------


class TestExpandPath:
    def test_single_absolute_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello")
        result = _expand_path(str(f), tmp_path)
        assert result == [(f, str(f))]

    def test_single_relative_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello")
        result = _expand_path("doc.md", tmp_path)
        assert result == [(tmp_path / "doc.md", "doc.md")]

    def test_depth1_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "b.md").write_text("b")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "c.md").write_text("c")

        result = _expand_path(str(tmp_path), tmp_path)
        resolved = [r for r, _ in result]
        assert tmp_path / "a.md" in resolved
        assert tmp_path / "b.md" in resolved
        assert sub / "c.md" not in resolved  # depth-1 only

    def test_recursive_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("a")
        sub = tmp_path / "nested"
        sub.mkdir()
        (sub / "b.md").write_text("b")

        result = _expand_path(str(tmp_path) + "/**", tmp_path)
        resolved = [r for r, _ in result]
        assert tmp_path / "a.md" in resolved
        assert sub / "b.md" in resolved

    def test_nonexistent_path_returns_empty(self, tmp_path):
        result = _expand_path(str(tmp_path / "missing.md"), tmp_path)
        assert result == []

    def test_empty_directory_returns_empty(self, tmp_path):
        result = _expand_path(str(tmp_path), tmp_path)
        assert result == []

    def test_lexicographic_ordering(self, tmp_path):
        (tmp_path / "c.md").write_text("c")
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "b.md").write_text("b")

        result = _expand_path(str(tmp_path), tmp_path)
        names = [r.name for r, _ in result]
        assert names == sorted(names)

    def test_recursive_lexicographic_ordering(self, tmp_path):
        (tmp_path / "z.md").write_text("z")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("a")

        result = _expand_path(str(tmp_path) + "/**", tmp_path)
        paths = [str(r) for r, _ in result]
        assert paths == sorted(paths)

    def test_display_path_relative_file_is_declared(self, tmp_path):
        f = tmp_path / "standards.md"
        f.write_text("ok")
        result = _expand_path("standards.md", tmp_path)
        _, display = result[0]
        assert display == "standards.md"

    def test_display_path_directory_expanded_is_full_path(self, tmp_path):
        f = tmp_path / "tokens.md"
        f.write_text("ok")
        result = _expand_path(str(tmp_path), tmp_path)
        _, display = result[0]
        assert display == str(tmp_path / "tokens.md")


# ---------------------------------------------------------------------------
# _read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_valid_utf8(self, tmp_path):
        f = tmp_path / "ok.md"
        f.write_text("hello world", encoding="utf-8")
        assert _read_file(f, "ok.md", "agent") == "hello world"

    def test_missing_file_returns_none(self, tmp_path):
        result = _read_file(tmp_path / "ghost.md", "ghost.md", "agent")
        assert result is None

    def test_missing_file_logs_warning(self, tmp_path, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="agentharness.context_files"):
            _read_file(tmp_path / "ghost.md", "ghost.md", "myagent")
        assert "Context file not found" in caplog.text
        assert "myagent" in caplog.text

    def test_permission_error_returns_none(self):
        path = FIXTURES / "unreadable.md"
        if not path.exists():
            pytest.skip("fixture not found")
        if os.access(path, os.R_OK):
            pytest.skip("file is readable — cannot test permission error")
        result = _read_file(path, str(path), "agent")
        assert result is None

    def test_permission_error_logs_warning(self, caplog):
        path = FIXTURES / "unreadable.md"
        if not path.exists():
            pytest.skip("fixture not found")
        if os.access(path, os.R_OK):
            pytest.skip("file is readable — cannot test permission error")
        import logging
        with caplog.at_level(logging.WARNING, logger="agentharness.context_files"):
            _read_file(path, str(path), "myagent")
        assert "Context file unreadable" in caplog.text

    def test_binary_file_returns_none(self):
        result = _read_file(FIXTURES / "binary.png", "binary.png", "agent")
        assert result is None

    def test_binary_file_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="agentharness.context_files"):
            _read_file(FIXTURES / "binary.png", "binary.png", "myagent")
        assert "not valid UTF-8" in caplog.text


# ---------------------------------------------------------------------------
# resolve_context_files
# ---------------------------------------------------------------------------


class TestResolveContextFiles:
    def test_happy_path_single_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("content")
        result = resolve_context_files([str(f)], "agent", tmp_path)
        assert len(result.files) == 1
        assert result.files[0].content == "content"
        assert result.warnings == ()

    def test_happy_path_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("aaa")
        (tmp_path / "b.md").write_text("bbb")
        result = resolve_context_files([str(tmp_path)], "agent", tmp_path)
        assert len(result.files) == 2

    def test_happy_path_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "top.md").write_text("top")
        (sub / "deep.md").write_text("deep")
        result = resolve_context_files([str(tmp_path) + "/**"], "agent", tmp_path)
        assert len(result.files) == 2

    def test_all_missing_paths_returns_empty_files_with_warnings(self, tmp_path):
        result = resolve_context_files(
            [str(tmp_path / "x.md"), str(tmp_path / "y.md")], "agent", tmp_path
        )
        assert result.files == ()
        assert len(result.warnings) == 0  # warnings come from _read_file skips, missing dirs are logged not warned

    def test_empty_declared_paths(self, tmp_path):
        result = resolve_context_files([], "agent", tmp_path)
        assert result.files == ()
        assert result.warnings == ()
        assert result.total_bytes == 0

    def test_total_bytes_computed(self, tmp_path):
        content = "hello"
        f = tmp_path / "f.md"
        f.write_text(content, encoding="utf-8")
        result = resolve_context_files([str(f)], "agent", tmp_path)
        assert result.total_bytes == len(content.encode("utf-8"))

    def test_size_warning_logged_when_over_threshold(self, tmp_path, caplog):
        import logging
        large = "x" * 52_000
        f = tmp_path / "big.md"
        f.write_text(large, encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="agentharness.context_files"):
            resolve_context_files([str(f)], "agent", tmp_path)
        assert "exceeding 50 KB" in caplog.text

    def test_no_size_warning_below_threshold(self, tmp_path, caplog):
        import logging
        f = tmp_path / "small.md"
        f.write_text("small", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="agentharness.context_files"):
            resolve_context_files([str(f)], "agent", tmp_path)
        assert "exceeding 50 KB" not in caplog.text

    def test_skips_binary_but_includes_valid(self, tmp_path):
        good = tmp_path / "good.md"
        good.write_text("valid")
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"\xff\xfe binary")
        result = resolve_context_files([str(good), str(bad)], "agent", tmp_path)
        assert len(result.files) == 1
        assert result.files[0].content == "valid"

    def test_result_is_immutable(self, tmp_path):
        f = tmp_path / "f.md"
        f.write_text("ok")
        result = resolve_context_files([str(f)], "agent", tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            result.agent_name = "other"  # type: ignore[misc]

    def test_relative_path_resolved_against_config_dir(self, tmp_path):
        f = tmp_path / "rel.md"
        f.write_text("relative")
        result = resolve_context_files(["rel.md"], "agent", tmp_path)
        assert len(result.files) == 1
        assert result.files[0].content == "relative"

    def test_display_path_relative_file_keeps_declared(self, tmp_path):
        f = tmp_path / "standards.md"
        f.write_text("ok")
        result = resolve_context_files(["standards.md"], "agent", tmp_path)
        assert result.files[0].display_path == "standards.md"


# ---------------------------------------------------------------------------
# format_context_section
# ---------------------------------------------------------------------------


class TestFormatContextSection:
    def test_empty_tuple_returns_empty_string(self):
        assert format_context_section(()) == ""

    def test_single_file_format(self, tmp_path):
        f = ResolvedContextFile(
            declared_path="/docs/a.md",
            resolved_path=tmp_path / "a.md",
            display_path="/docs/a.md",
            content="# Title\nBody.",
            size_bytes=14,
        )
        result = format_context_section((f,))
        assert "## Agent Context Files" in result
        assert "### Context: /docs/a.md" in result
        assert "# Title\nBody." in result

    def test_multiple_files_separated_by_blank_line(self, tmp_path):
        files = tuple(
            ResolvedContextFile(
                declared_path=f"/docs/{i}.md",
                resolved_path=tmp_path / f"{i}.md",
                display_path=f"/docs/{i}.md",
                content=f"content {i}",
                size_bytes=9,
            )
            for i in range(3)
        )
        result = format_context_section(files)
        assert result.count("### Context:") == 3
        assert "## Agent Context Files" in result
        # blocks separated by blank line
        assert "\n\n### Context:" in result

    def test_header_appears_once(self, tmp_path):
        files = tuple(
            ResolvedContextFile(
                declared_path=f"/f{i}.md",
                resolved_path=tmp_path / f"f{i}.md",
                display_path=f"/f{i}.md",
                content="c",
                size_bytes=1,
            )
            for i in range(2)
        )
        result = format_context_section(files)
        assert result.count("## Agent Context Files") == 1
