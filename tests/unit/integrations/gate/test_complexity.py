"""Tests for devflow.integrations.gate.complexity."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate.complexity import check_complexity


class TestCheckComplexity:
    """Tests for the C901 complexity check."""

    @patch("devflow.integrations.gate.complexity.subprocess.run")
    def test_no_violations(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"], returncode=0, stdout="", stderr="",
        )
        result = check_complexity(base=tmp_path)
        assert result.passed is True
        assert result.name == "complexity"
        assert "No complex" in result.message

    @patch("devflow.integrations.gate.complexity.subprocess.run")
    def test_violations_reported_as_warning(self, mock_run: patch, tmp_path: Path) -> None:
        stdout = (
            "src/foo.py:10:1: C901 'bar' is too complex (15)\n"
            "src/baz.py:20:1: C901 'qux' is too complex (12)\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"], returncode=1, stdout=stdout, stderr="",
        )
        result = check_complexity(base=tmp_path)
        # WARNING: passed=True even though violations exist
        assert result.passed is True
        assert "2 function(s)" in result.message
        assert "warning" in result.message
        assert "src/foo.py" in result.details
        assert "src/baz.py" in result.details

    @patch("devflow.integrations.gate.complexity.subprocess.run")
    def test_custom_max_complexity(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"], returncode=0, stdout="", stderr="",
        )
        check_complexity(base=tmp_path, max_complexity=15)
        cmd = mock_run.call_args[0][0]
        assert any("15" in arg for arg in cmd)

    @patch(
        "devflow.integrations.gate.complexity.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_ruff_missing_skipped(self, _mock: patch, tmp_path: Path) -> None:
        result = check_complexity(base=tmp_path)
        assert result.skipped is True
        assert result.passed is False
        assert "not found" in result.message

    @patch(
        "devflow.integrations.gate.complexity.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["ruff"], timeout=60),
    )
    def test_timeout(self, _mock: patch, tmp_path: Path) -> None:
        result = check_complexity(base=tmp_path)
        assert result.passed is False
        assert "timed out" in result.message

    @patch("devflow.integrations.gate.complexity.subprocess.run")
    def test_nonzero_exit_but_empty_stdout(self, mock_run: patch, tmp_path: Path) -> None:
        """ruff returns nonzero but no output (e.g. config error)."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"], returncode=1, stdout="", stderr="config error",
        )
        result = check_complexity(base=tmp_path)
        assert result.passed is True
        assert "No complex" in result.message

    @patch("devflow.integrations.gate.complexity.subprocess.run")
    def test_details_truncated(self, mock_run: patch, tmp_path: Path) -> None:
        stdout = "x\n" * 3000
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"], returncode=1, stdout=stdout, stderr="",
        )
        result = check_complexity(base=tmp_path)
        assert len(result.details) <= 2000
