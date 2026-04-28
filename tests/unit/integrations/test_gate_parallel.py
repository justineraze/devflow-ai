"""Tests for parallel gate execution and structured report serialization."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from devflow.integrations.gate import CheckResult, GateReport, run_gate
from devflow.integrations.gate.context import GateContext

_AUDIT_CTX = GateContext(mode="audit")


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
            "duration_s": 0.0,
        }

    def test_duration_s_is_rounded_to_3_decimals(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="lint", passed=True, duration_s=1.23456789))
        data = report.to_dict()
        assert data["checks"][0]["duration_s"] == 1.235

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
            "devflow.integrations.gate.runner.run_command_check",
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
            report = run_gate(_AUDIT_CTX, base=tmp_path, stack="python")
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
            "devflow.integrations.gate.runner.run_command_check",
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
            report = run_gate(_AUDIT_CTX, base=tmp_path, stack="python")

        names = [c.name for c in report.checks]
        assert names == ["ruff", "pytest", "secrets", "complexity", "module_size"]


class TestCheckTiming:
    def test_check_result_duration_defaults_to_zero(self) -> None:
        result = CheckResult(name="lint", passed=True)
        assert result.duration_s == 0.0

    def test_timed_stamps_duration(self, tmp_path: Path) -> None:
        """_timed wrapper must populate duration_s with elapsed time."""
        from devflow.integrations.gate.runner import _timed

        def slow() -> CheckResult:
            time.sleep(0.05)
            return CheckResult(name="x", passed=True)

        result = _timed(slow)
        assert result.duration_s >= 0.04, f"expected ≥40ms, got {result.duration_s:.3f}s"

    def test_run_gate_stamps_durations(self, tmp_path: Path) -> None:
        """All checks in the report must have a non-zero duration after run_gate."""
        def instant(*_args, **_kwargs) -> CheckResult:
            time.sleep(0.01)
            return CheckResult(name="fake", passed=True)

        with patch(
            "devflow.integrations.gate.runner.run_command_check",
            side_effect=instant,
        ), patch(
            "devflow.integrations.gate.runner.scan_secrets",
            side_effect=instant,
        ), patch(
            "devflow.integrations.gate.runner.check_complexity",
            side_effect=instant,
        ), patch(
            "devflow.integrations.gate.runner.check_module_size",
            side_effect=instant,
        ):
            report = run_gate(_AUDIT_CTX, base=tmp_path, stack="python")

        for check in report.checks:
            assert check.duration_s > 0, f"{check.name}: duration_s should be > 0"
