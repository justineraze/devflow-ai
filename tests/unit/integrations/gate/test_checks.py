"""Tests for devflow.integrations.gate.checks.

Covers: _parse_pytest, run_command_check, checks_for_stack, STACK_CHECKS.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate.checks import (
    STACK_CHECKS,
    CheckDef,
    _parse_pytest,
    checks_for_stack,
    run_command_check,
)


class TestParsePytest:
    """Tests for the pure _parse_pytest helper."""

    def test_returncode_zero_returns_last_line(self) -> None:
        message, details = _parse_pytest(0, "collected 5\n5 passed in 0.1s\n")
        assert message == "5 passed in 0.1s"
        assert details == ""

    def test_returncode_nonzero_returns_last_line_and_truncated_details(self) -> None:
        stdout = "failure\n" * 300  # well over 2000 chars
        message, details = _parse_pytest(1, stdout)
        assert message == "failure"
        assert len(details) <= 2000

    def test_returncode_nonzero_empty_stdout_returns_fallback(self) -> None:
        message, details = _parse_pytest(1, "")
        assert message == "Tests failed"
        assert details == ""


class TestRunCommandCheck:
    """Tests for the generic run_command_check helper."""

    @patch("devflow.integrations.gate.checks.subprocess.run")
    def test_success(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tool"], returncode=0, stdout="all good\n", stderr="",
        )
        result = run_command_check("tool", ["tool", "check"], cwd=tmp_path)
        assert result.passed is True
        assert result.message == "No issues"

    @patch("devflow.integrations.gate.checks.subprocess.run")
    def test_failure(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tool"], returncode=1, stdout="error line 1\nerror line 2\n", stderr="",
        )
        result = run_command_check("tool", ["tool", "check"], cwd=tmp_path)
        assert result.passed is False
        assert "issues found" in result.message

    @patch("devflow.integrations.gate.checks.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_tool_skipped(self, _mock: patch, tmp_path: Path) -> None:
        result = run_command_check("biome", ["npx", "biome", "check"], cwd=tmp_path)
        assert result.skipped is True
        assert result.passed is True
        assert "not found" in result.message

    @patch(
        "devflow.integrations.gate.checks.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["tool"], timeout=60),
    )
    def test_timeout(self, _mock: patch, tmp_path: Path) -> None:
        result = run_command_check("tool", ["tool", "check"], cwd=tmp_path, timeout=60)
        assert result.passed is False
        assert "timed out" in result.message

    @patch("devflow.integrations.gate.checks.subprocess.run")
    def test_custom_parse_output(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["t"], returncode=0, stdout="5 passed in 0.1s\n", stderr="",
        )

        def _parse(rc: int, stdout: str) -> tuple[str, str]:
            return stdout.strip().split("\n")[-1], ""

        result = run_command_check(
            "pytest", ["pytest"], cwd=tmp_path, parse_output=_parse,
        )
        assert result.passed is True
        assert result.message == "5 passed in 0.1s"

    @patch("devflow.integrations.gate.checks.subprocess.run")
    def test_stderr_fallback_when_stdout_empty(self, mock_run: patch, tmp_path: Path) -> None:
        """When stdout is empty, details come from stderr."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["python", "-m", "pytest"],
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'missing_pkg'",
        )
        result = run_command_check("pytest", ["python", "-m", "pytest"], cwd=tmp_path)
        assert result.passed is False
        assert "ModuleNotFoundError" in result.details

    @patch("devflow.integrations.gate.checks.subprocess.run")
    def test_cwd_and_env_passed_to_subprocess(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tool"], returncode=0, stdout="", stderr="",
        )
        run_command_check("tool", ["tool"], cwd=tmp_path)
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)
        assert "env" in mock_run.call_args.kwargs


class TestChecksForStack:
    """Tests for checks_for_stack stack→tools mapping."""

    def test_python_stack(self) -> None:
        checks = checks_for_stack("python")
        names = [c[0] for c in checks]
        assert names == ["ruff", "pytest"]

    def test_typescript_stack(self) -> None:
        checks = checks_for_stack("typescript")
        names = [c[0] for c in checks]
        assert names == ["biome", "vitest"]

    def test_php_stack(self) -> None:
        checks = checks_for_stack("php")
        names = [c[0] for c in checks]
        assert names == ["pint", "pest"]

    def test_none_defaults_to_python(self) -> None:
        checks = checks_for_stack(None)
        assert checks is STACK_CHECKS["python"]

    def test_unknown_defaults_to_python(self) -> None:
        checks = checks_for_stack("ruby")
        assert checks is STACK_CHECKS["python"]


class TestStackChecksRegistry:
    """Structural validation of the STACK_CHECKS registry."""

    def test_all_entries_are_valid_check_defs(self) -> None:
        for stack, checks in STACK_CHECKS.items():
            assert isinstance(checks, tuple), f"{stack}: expected tuple"
            assert len(checks) > 0, f"{stack}: checks tuple is empty"
            for check in checks:
                assert isinstance(check, CheckDef), f"{stack}/{check}: not a CheckDef"
                assert isinstance(check.cmd, list), f"{stack}/{check.name}: cmd not a list"
                assert len(check.cmd) > 0, f"{stack}/{check.name}: cmd is empty"
                assert check.timeout > 0, f"{stack}/{check.name}: timeout <= 0"
