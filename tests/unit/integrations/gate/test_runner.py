"""Tests for devflow.integrations.gate.runner — run_gate."""

from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate import CheckResult, run_gate
from devflow.integrations.gate.context import GateContext

_OK = CheckResult(name="x", passed=True, message="ok")
_SECRETS_OK = CheckResult(name="secrets", passed=True, message="clean")
_COMPLEXITY_OK = CheckResult(name="complexity", passed=True, message="ok")
_MODULE_SIZE_OK = CheckResult(name="module_size", passed=True, message="ok")

_AUDIT_CTX = GateContext(mode="audit")


def _patch_structural(fn):
    """Decorator to mock the two structural checks alongside secrets."""
    _mod = "devflow.integrations.gate.runner"
    fn = patch(f"{_mod}.check_module_size", return_value=_MODULE_SIZE_OK)(fn)
    fn = patch(f"{_mod}.check_complexity", return_value=_COMPLEXITY_OK)(fn)
    return fn


class TestRunGate:
    """Tests for run_gate stack dispatch."""

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_uses_typescript_tools(
        self, mock_secrets: patch, mock_check: patch,
        _mock_cx: patch, _mock_ms: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK

        run_gate(_AUDIT_CTX, base=tmp_path, stack="typescript")

        assert mock_check.call_count == 2
        call_names = [call.args[0] for call in mock_check.call_args_list]
        assert call_names == ["biome", "vitest"]

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_default_stack_is_python(
        self, mock_secrets: patch, mock_check: patch,
        _mock_cx: patch, _mock_ms: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK

        run_gate(_AUDIT_CTX, base=tmp_path)

        call_names = [call.args[0] for call in mock_check.call_args_list]
        assert call_names == ["ruff", "pytest"]

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_secrets_always_runs(
        self, mock_secrets: patch, mock_check: patch,
        _mock_cx: patch, _mock_ms: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK

        report = run_gate(_AUDIT_CTX, base=tmp_path, stack="php")

        mock_secrets.assert_called_once()
        check_names = [c.name for c in report.checks]
        assert "secrets" in check_names

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_structural_checks_included_in_report(
        self, mock_secrets: patch, mock_check: patch,
        _mock_cx: patch, _mock_ms: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK

        report = run_gate(_AUDIT_CTX, base=tmp_path)

        check_names = [c.name for c in report.checks]
        assert "complexity" in check_names
        assert "module_size" in check_names

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_structural_warnings_dont_fail_gate(
        self, mock_secrets: patch, mock_check: patch,
        mock_cx: patch, mock_ms: patch, tmp_path: Path,
    ) -> None:
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK
        mock_cx.return_value = CheckResult(
            name="complexity", passed=True,
            message="2 function(s) exceed complexity 10 (warning)",
        )
        mock_ms.return_value = CheckResult(
            name="module_size", passed=True,
            message="1 module(s) exceed 400 lines (warning)",
        )

        report = run_gate(_AUDIT_CTX, base=tmp_path)
        assert report.passed is True

    @_patch_structural
    @patch("devflow.integrations.gate.runner._run_command_check")
    @patch("devflow.integrations.gate.runner.scan_secrets")
    def test_context_passed_to_structural_checks(
        self, mock_secrets: patch, mock_check: patch,
        mock_cx: patch, mock_ms: patch, tmp_path: Path,
    ) -> None:
        """Verify that the GateContext is forwarded to secrets/complexity/module_size."""
        mock_check.return_value = _OK
        mock_secrets.return_value = _SECRETS_OK
        mock_cx.return_value = _COMPLEXITY_OK
        mock_ms.return_value = _MODULE_SIZE_OK

        ctx = GateContext(mode="build", changed_files=[Path("src/app.py")])
        run_gate(ctx, base=tmp_path)

        # secrets receives ctx as second positional arg
        mock_secrets.assert_called_once_with(tmp_path, ctx)
        # complexity and module_size receive ctx as keyword arg
        mock_cx.assert_called_once_with(tmp_path, ctx=ctx)
        mock_ms.assert_called_once_with(tmp_path, ctx=ctx)
