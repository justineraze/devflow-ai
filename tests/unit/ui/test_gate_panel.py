"""Tests for gate_panel Rich rendering, including verbose timing display."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from devflow.core.gate_report import CheckResult, GateReport
from devflow.ui import gate_panel as gp


def _render(report: GateReport, *, verbose: bool = False) -> str:
    """Render *report* into a string and return the captured output."""
    buf = io.StringIO()
    con = Console(file=buf, width=120, force_terminal=False, no_color=True)
    mp = pytest.MonkeyPatch()
    mp.setattr(gp, "console", con)
    try:
        gp.render_gate_report(report, verbose=verbose)
    finally:
        mp.undo()
    return buf.getvalue()


class TestRenderGateReportVerbose:
    def test_no_timing_by_default(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="lint", passed=True, message="ok", duration_s=1.23))
        output = _render(report, verbose=False)
        assert "1.23" not in output

    def test_verbose_shows_duration(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="lint", passed=True, message="ok", duration_s=1.5))
        output = _render(report, verbose=True)
        assert "1.50s" in output

    def test_verbose_hides_zero_duration(self) -> None:
        """Checks with duration_s=0 should not show timing even in verbose mode."""
        report = GateReport()
        report.add(CheckResult(name="lint", passed=True, message="ok", duration_s=0.0))
        output = _render(report, verbose=True)
        assert "(0.00s)" not in output

    def test_verbose_shows_timing_for_all_checks(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="lint", passed=True, message="ok", duration_s=0.5))
        report.add(CheckResult(name="test", passed=False, message="2 failed", duration_s=3.2))
        output = _render(report, verbose=True)
        assert "0.50s" in output
        assert "3.20s" in output

    def test_verbose_skipped_check_shows_timing(self) -> None:
        report = GateReport()
        report.add(CheckResult(
            name="secrets", passed=True, skipped=True, message="skipped", duration_s=0.1,
        ))
        output = _render(report, verbose=True)
        assert "0.10s" in output
