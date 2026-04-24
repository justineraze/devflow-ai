"""Tests for devflow.integrations.gate.module_size."""

from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate.module_size import (
    _count_non_empty_lines,
    _modified_py_files,
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


class TestModifiedPyFiles:
    """Tests for _modified_py_files git integration."""

    @patch("devflow.integrations.gate.module_size.subprocess.run")
    def test_filters_src_py_files(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = type("R", (), {
            "returncode": 0,
            "stdout": "src/devflow/cli.py\nsrc/devflow/core/models.py\n"
                      "README.md\ntests/test_x.py\n",
        })()
        files = _modified_py_files(tmp_path)
        assert files == ["src/devflow/cli.py", "src/devflow/core/models.py"]

    @patch("devflow.integrations.gate.module_size.subprocess.run", side_effect=FileNotFoundError)
    def test_git_missing_returns_empty(self, _mock: patch, tmp_path: Path) -> None:
        assert _modified_py_files(tmp_path) == []

    @patch("devflow.integrations.gate.module_size.subprocess.run")
    def test_git_error_returns_empty(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = type("R", (), {"returncode": 128, "stdout": ""})()
        assert _modified_py_files(tmp_path) == []


class TestCheckModuleSize:
    """Tests for the module size gate check."""

    @patch("devflow.integrations.gate.module_size._modified_py_files")
    def test_no_modified_files(self, mock_files: patch, tmp_path: Path) -> None:
        mock_files.return_value = []
        result = check_module_size(base=tmp_path)
        assert result.passed is True
        assert "No modified" in result.message

    @patch("devflow.integrations.gate.module_size._modified_py_files")
    def test_all_within_limit(self, mock_files: patch, tmp_path: Path) -> None:
        # Create a small file
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        f = src / "small.py"
        f.write_text("x = 1\n" * 10)
        mock_files.return_value = ["src/devflow/small.py"]

        result = check_module_size(base=tmp_path, max_lines=400)
        assert result.passed is True
        assert "within size limit" in result.message

    @patch("devflow.integrations.gate.module_size._modified_py_files")
    def test_oversized_reported_as_warning(self, mock_files: patch, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        f = src / "big.py"
        f.write_text("x = 1\n" * 500)
        mock_files.return_value = ["src/devflow/big.py"]

        result = check_module_size(base=tmp_path, max_lines=400)
        # WARNING: passed=True even though violation exists
        assert result.passed is True
        assert "1 module(s)" in result.message
        assert "warning" in result.message
        assert "src/devflow/big.py" in result.details
        assert "500 lines" in result.details

    @patch("devflow.integrations.gate.module_size._modified_py_files")
    def test_custom_max_lines(self, mock_files: patch, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        f = src / "mod.py"
        f.write_text("x = 1\n" * 50)
        mock_files.return_value = ["src/devflow/mod.py"]

        result = check_module_size(base=tmp_path, max_lines=30)
        assert "1 module(s)" in result.message

    @patch("devflow.integrations.gate.module_size._modified_py_files")
    def test_missing_file_ignored(self, mock_files: patch, tmp_path: Path) -> None:
        mock_files.return_value = ["src/devflow/deleted.py"]
        result = check_module_size(base=tmp_path)
        assert result.passed is True
