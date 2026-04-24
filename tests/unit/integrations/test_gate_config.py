"""Tests for custom gate configuration loading and custom check execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from devflow.integrations.gate.config import load_gate_config
from devflow.integrations.gate.context import GateContext
from devflow.integrations.gate.report import GateReport
from devflow.integrations.gate.runner import _run_custom_check, run_gate

_AUDIT_CTX = GateContext(mode="audit")


class TestLoadGateConfig:
    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        (tmp_path / ".devflow").mkdir()
        assert load_gate_config(tmp_path) is None

    def test_returns_none_for_empty_gate_section(self, tmp_path: Path) -> None:
        (tmp_path / ".devflow").mkdir()
        (tmp_path / ".devflow" / "config.yaml").write_text(
            yaml.dump({"stack": "python"})
        )
        assert load_gate_config(tmp_path) is None

    def test_loads_lint_and_test_from_config_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".devflow").mkdir()
        (tmp_path / ".devflow" / "config.yaml").write_text(
            yaml.dump({"gate": {"lint": "make check", "test": "make test"}})
        )
        config = load_gate_config(tmp_path)
        assert config == {"lint": "make check", "test": "make test"}

    def test_loads_lint_only(self, tmp_path: Path) -> None:
        (tmp_path / ".devflow").mkdir()
        (tmp_path / ".devflow" / "config.yaml").write_text(
            yaml.dump({"gate": {"lint": "ruff check ."}})
        )
        config = load_gate_config(tmp_path)
        assert config == {"lint": "ruff check ."}

    def test_migrates_legacy_gate_yaml(self, tmp_path: Path) -> None:
        """Legacy gate.yaml is migrated into config.yaml on load."""
        (tmp_path / ".devflow").mkdir()
        (tmp_path / ".devflow" / "gate.yaml").write_text("lint: make check\ntest: make test\n")
        config = load_gate_config(tmp_path)
        assert config == {"lint": "make check", "test": "make test"}
        # gate.yaml should be deleted after migration.
        assert not (tmp_path / ".devflow" / "gate.yaml").exists()


class TestRunCustomCheck:
    def test_passing_command(self, tmp_path: Path) -> None:
        result = _run_custom_check("lint", "true", tmp_path)
        assert result.passed is True
        assert result.name == "lint"

    def test_failing_command(self, tmp_path: Path) -> None:
        result = _run_custom_check("test", "false", tmp_path)
        assert result.passed is False
        assert "failed" in result.message

    def test_command_with_output(self, tmp_path: Path) -> None:
        result = _run_custom_check("lint", "echo 'hello world'", tmp_path)
        assert result.passed is True

    def test_timeout(self, tmp_path: Path) -> None:
        with patch(
            "devflow.integrations.gate.runner._CUSTOM_TIMEOUTS",
            {"lint": 1},
        ):
            result = _run_custom_check("lint", "sleep 10", tmp_path)
        assert result.passed is False
        assert "timed out" in result.message


class TestRunGateWithCustomConfig:
    def test_uses_custom_config_when_present(self, tmp_path: Path) -> None:
        """When config.yaml has gate commands, custom commands run instead of stack checks."""
        (tmp_path / ".devflow").mkdir()
        (tmp_path / ".devflow" / "config.yaml").write_text(
            yaml.dump({"gate": {"lint": "echo ok", "test": "echo ok"}})
        )

        with patch(
            "devflow.integrations.gate.runner.scan_secrets",
            return_value=__import__(
                "devflow.integrations.gate.report", fromlist=["CheckResult"]
            ).CheckResult(name="secrets", passed=True),
        ), patch(
            "devflow.integrations.gate.runner.check_complexity",
            return_value=__import__(
                "devflow.integrations.gate.report", fromlist=["CheckResult"]
            ).CheckResult(name="complexity", passed=True),
        ), patch(
            "devflow.integrations.gate.runner.check_module_size",
            return_value=__import__(
                "devflow.integrations.gate.report", fromlist=["CheckResult"]
            ).CheckResult(name="module_size", passed=True),
        ):
            report = run_gate(_AUDIT_CTX, base=tmp_path)

        assert report.custom is True
        assert report.passed is True
        names = [c.name for c in report.checks]
        assert "lint" in names
        assert "test" in names
        assert "secrets" in names

    def test_falls_back_to_stack_when_no_config(self, tmp_path: Path) -> None:
        """Without gate config, stack detection is used as before."""
        from devflow.integrations.gate.report import CheckResult

        def fake_run(*_args, **_kw) -> CheckResult:
            return CheckResult(name="fake", passed=True)

        with patch(
            "devflow.integrations.gate.runner._run_command_check",
            side_effect=fake_run,
        ), patch(
            "devflow.integrations.gate.runner.scan_secrets",
            return_value=CheckResult(name="secrets", passed=True),
        ), patch(
            "devflow.integrations.gate.runner.check_complexity",
            return_value=CheckResult(name="complexity", passed=True),
        ), patch(
            "devflow.integrations.gate.runner.check_module_size",
            return_value=CheckResult(name="module_size", passed=True),
        ):
            report = run_gate(_AUDIT_CTX, base=tmp_path, stack="python")

        assert report.custom is False

    def test_custom_flag_in_to_dict(self) -> None:
        report = GateReport(custom=True)
        assert report.to_dict()["custom"] is True

        report2 = GateReport()
        assert report2.to_dict()["custom"] is False
