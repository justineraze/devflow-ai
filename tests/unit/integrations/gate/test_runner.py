"""Tests for devflow.integrations.gate.runner — run_gate."""

from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate import CheckResult, run_gate


class TestRunGate:
    """Tests for run_gate stack dispatch."""

    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_uses_typescript_tools(
        self, mock_secrets: patch, mock_check: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = CheckResult(name="x", passed=True, message="ok")
        mock_secrets.return_value = CheckResult(
            name="secrets", passed=True, message="clean",
        )

        run_gate(base=tmp_path, stack="typescript")

        assert mock_check.call_count == 2
        call_names = [call.args[0] for call in mock_check.call_args_list]
        assert call_names == ["biome", "vitest"]

    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_default_stack_is_python(
        self, mock_secrets: patch, mock_check: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = CheckResult(name="x", passed=True, message="ok")
        mock_secrets.return_value = CheckResult(
            name="secrets", passed=True, message="clean",
        )

        run_gate(base=tmp_path)

        call_names = [call.args[0] for call in mock_check.call_args_list]
        assert call_names == ["ruff", "pytest"]

    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_secrets_always_runs(
        self, mock_secrets: patch, mock_check: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = CheckResult(name="x", passed=True, message="ok")
        mock_secrets.return_value = CheckResult(
            name="secrets", passed=True, message="clean",
        )

        report = run_gate(base=tmp_path, stack="php")

        mock_secrets.assert_called_once()
        check_names = [c.name for c in report.checks]
        assert "secrets" in check_names
