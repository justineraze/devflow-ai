"""Tests for devflow.integrations.gate.module_size."""

from pathlib import Path

from devflow.integrations.gate.context import GateContext
from devflow.integrations.gate.module_size import (
    _count_non_empty_lines,
    check_module_size,
)


class TestCountNonEmptyLines:
    """Tests for the line counting helper."""

    def test_counts_non_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("import os\n\ndef foo():\n    pass\n\n")
        assert _count_non_empty_lines(f) == 3

    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        assert _count_non_empty_lines(tmp_path / "nope.py") == 0

    def test_empty_file_returns_zero(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _count_non_empty_lines(f) == 0


class TestCheckModuleSizeAudit:
    """Tests for module_size in audit mode (scan all src/)."""

    def test_no_src_dir(self, tmp_path: Path) -> None:
        ctx = GateContext(mode="audit")
        result = check_module_size(base=tmp_path, ctx=ctx)
        assert result.passed is True
        assert "No modules" in result.message

    def test_all_within_limit(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "small.py").write_text("x = 1\n" * 10)

        ctx = GateContext(mode="audit")
        result = check_module_size(base=tmp_path, max_lines=400, ctx=ctx)
        assert result.passed is True
        assert "within size limit" in result.message

    def test_oversized_reported_as_warning(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "big.py").write_text("x = 1\n" * 500)

        ctx = GateContext(mode="audit")
        result = check_module_size(base=tmp_path, max_lines=400, ctx=ctx)
        assert result.passed is True
        assert "1 module(s)" in result.message
        assert "warning" in result.message


class TestCheckModuleSizeBuild:
    """Tests for module_size in build mode (scoped to changed files)."""

    def test_build_mode_only_checks_changed_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "big.py").write_text("x = 1\n" * 500)
        (src / "small.py").write_text("x = 1\n" * 10)

        # Only small.py is in the diff → big.py is ignored.
        ctx = GateContext(
            mode="build",
            changed_files=[Path("src/devflow/small.py")],
        )
        result = check_module_size(base=tmp_path, max_lines=400, ctx=ctx)
        assert result.passed is True
        assert "within size limit" in result.message

    def test_build_mode_detects_oversized_changed_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "big.py").write_text("x = 1\n" * 500)

        ctx = GateContext(
            mode="build",
            changed_files=[Path("src/devflow/big.py")],
        )
        result = check_module_size(base=tmp_path, max_lines=400, ctx=ctx)
        assert "1 module(s)" in result.message
        assert "500 lines" in result.details

    def test_build_mode_no_src_files(self, tmp_path: Path) -> None:
        ctx = GateContext(
            mode="build",
            changed_files=[Path("README.md"), Path("tests/test_x.py")],
        )
        result = check_module_size(base=tmp_path, ctx=ctx)
        assert result.passed is True
        assert "No files" in result.message

    def test_build_mode_excludes_patterns(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "vendor"
        src.mkdir(parents=True)
        (src / "big.py").write_text("x = 1\n" * 500)

        ctx = GateContext(
            mode="build",
            changed_files=[Path("src/vendor/big.py")],
            exclude_patterns=["src/vendor/**"],
        )
        result = check_module_size(base=tmp_path, max_lines=400, ctx=ctx)
        assert result.passed is True

    def test_build_mode_missing_file_ignored(self, tmp_path: Path) -> None:
        ctx = GateContext(
            mode="build",
            changed_files=[Path("src/devflow/deleted.py")],
        )
        result = check_module_size(base=tmp_path, ctx=ctx)
        assert result.passed is True

    def test_no_context_scans_src(self, tmp_path: Path) -> None:
        """Without context, behaves like audit (scan all src/)."""
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "big.py").write_text("x = 1\n" * 500)

        result = check_module_size(base=tmp_path, max_lines=400)
        assert "1 module(s)" in result.message
