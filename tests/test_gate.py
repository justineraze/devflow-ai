"""Tests for devflow.gate — quality gate checks."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from devflow.gate import (
    STACK_CHECKS,
    CheckResult,
    GateReport,
    _checks_for_stack,
    _run_command_check,
    scan_secrets,
)


class TestCheckResult:
    def test_passed_check(self) -> None:
        result = CheckResult(name="test", passed=True, message="OK")
        assert result.passed is True

    def test_failed_check(self) -> None:
        result = CheckResult(name="test", passed=False, message="FAIL")
        assert result.passed is False


class TestGateReport:
    def test_all_passed(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=True))
        assert report.passed is True

    def test_one_failed(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=False))
        assert report.passed is False

    def test_empty_report_passes(self) -> None:
        report = GateReport()
        assert report.passed is True


class TestRunCommandCheck:
    """Tests for the generic _run_command_check helper."""

    @patch("devflow.gate.subprocess.run")
    def test_success(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tool"], returncode=0, stdout="all good\n", stderr="",
        )
        result = _run_command_check("tool", ["tool", "check"], cwd=tmp_path)
        assert result.passed is True
        assert result.message == "No issues"

    @patch("devflow.gate.subprocess.run")
    def test_failure(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tool"], returncode=1, stdout="error line 1\nerror line 2\n", stderr="",
        )
        result = _run_command_check("tool", ["tool", "check"], cwd=tmp_path)
        assert result.passed is False
        assert "issues found" in result.message

    @patch("devflow.gate.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_tool_skipped(self, _mock: patch, tmp_path: Path) -> None:
        result = _run_command_check("biome", ["npx", "biome", "check"], cwd=tmp_path)
        assert result.passed is True
        assert "not found" in result.message
        assert "skipped" in result.message

    @patch(
        "devflow.gate.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["tool"], timeout=60),
    )
    def test_timeout(self, _mock: patch, tmp_path: Path) -> None:
        result = _run_command_check("tool", ["tool", "check"], cwd=tmp_path, timeout=60)
        assert result.passed is False
        assert "timed out" in result.message

    @patch("devflow.gate.subprocess.run")
    def test_custom_parse_output(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["t"], returncode=0, stdout="5 passed in 0.1s\n", stderr="",
        )

        def _parse(rc: int, stdout: str) -> tuple[str, str]:
            return stdout.strip().split("\n")[-1], ""

        result = _run_command_check(
            "pytest", ["pytest"], cwd=tmp_path, parse_output=_parse,
        )
        assert result.passed is True
        assert result.message == "5 passed in 0.1s"


class TestChecksForStack:
    """Tests for _checks_for_stack stack→tools mapping."""

    def test_python_stack(self) -> None:
        checks = _checks_for_stack("python")
        names = [c[0] for c in checks]
        assert names == ["ruff", "pytest"]

    def test_typescript_stack(self) -> None:
        checks = _checks_for_stack("typescript")
        names = [c[0] for c in checks]
        assert names == ["biome", "vitest"]

    def test_php_stack(self) -> None:
        checks = _checks_for_stack("php")
        names = [c[0] for c in checks]
        assert names == ["pint", "pest"]

    def test_none_defaults_to_python(self) -> None:
        checks = _checks_for_stack(None)
        assert checks is STACK_CHECKS["python"]

    def test_unknown_defaults_to_python(self) -> None:
        checks = _checks_for_stack("ruby")
        assert checks is STACK_CHECKS["python"]


class TestScanSecrets:
    def test_clean_project(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')")
        result = scan_secrets(tmp_path)
        assert result.passed is True

    def test_detects_aws_key(self, tmp_path: Path) -> None:
        (tmp_path / "config.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is False
        assert "AWS" in result.message or "secret" in result.message.lower()

    def test_detects_private_key(self, tmp_path: Path) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----"
        (tmp_path / "key.pem").write_text(pem)
        result = scan_secrets(tmp_path)
        assert result.passed is False

    def test_detects_api_key(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("api_key: 'sk_live_abcdefghijklmnopqrstuvwx'")
        result = scan_secrets(tmp_path)
        assert result.passed is False

    def test_skips_binary_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_text('key = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is True

    def test_skips_git_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text('secret = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is True
