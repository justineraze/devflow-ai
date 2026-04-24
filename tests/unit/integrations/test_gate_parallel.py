"""Tests for parallel gate execution and structured report serialization."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate import CheckResult, GateReport, run_gate


class TestToDict:
    def test_serializes_all_fields(self) -> None:
        report = GateReport()
        report.add(CheckResult(
            name="ruff", passed=False, message="2 issues", details="E501 line too long",
        ))
        report.add(CheckResult(name="pytest", passed=True, message="ok"))

        data = report.to_dict()

        assert data["passed"] is False
        assert len(data["checks"]) == 2
        assert data["checks"][0] == {
            "name": "ruff",
            "passed": False,
            "skipped": False,
            "message": "2 issues",
            "details": "E501 line too long",
        }

    def test_passed_is_true_when_all_pass(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=True))
        assert report.to_dict()["passed"] is True


class TestParallelExecution:
    def test_checks_run_concurrently(self, tmp_path: Path) -> None:
        """Three 100ms checks must finish in < 250ms when parallelized."""
        def slow_check(*_args, **_kwargs) -> CheckResult:
            time.sleep(0.1)
            return CheckResult(name="fake", passed=True, message="ok")

        with patch(
            "devflow.integrations.gate.runner._run_command_check",
            side_effect=slow_check,
        ), patch(
            "devflow.integrations.gate.runner.scan_secrets",
            side_effect=slow_check,
        ), patch(
            "devflow.integrations.gate.runner.check_complexity",
            side_effect=slow_check,
        ), patch(
            "devflow.integrations.gate.runner.check_module_size",
            side_effect=slow_check,
        ):
            start = time.monotonic()
            report = run_gate(base=tmp_path, stack="python")
            elapsed = time.monotonic() - start

        assert report.passed is True
        # Sequential would be 3 x 100ms = 300ms. Parallel should be ~100ms.
        assert elapsed < 0.25, f"expected parallel execution, got {elapsed:.2f}s"

    def test_report_order_is_stable(self, tmp_path: Path) -> None:
        """Parallel execution must preserve the declared check order."""
        def named(name: str):
            def _run(*_args, **_kwargs) -> CheckResult:
                return CheckResult(name=name, passed=True)
            return _run

        call_names: list[str] = []

        def capturing(check_name, *_rest, **_kw) -> CheckResult:
            call_names.append(check_name)
            return CheckResult(name=check_name, passed=True)

        with patch(
            "devflow.integrations.gate.runner._run_command_check",
            side_effect=capturing,
        ), patch(
            "devflow.integrations.gate.runner.scan_secrets",
            side_effect=named("secrets"),
        ), patch(
            "devflow.integrations.gate.runner.check_complexity",
            side_effect=named("complexity"),
        ), patch(
            "devflow.integrations.gate.runner.check_module_size",
            side_effect=named("module_size"),
        ):
            report = run_gate(base=tmp_path, stack="python")

        names = [c.name for c in report.checks]
        assert names == ["ruff", "pytest", "secrets", "complexity", "module_size"]
