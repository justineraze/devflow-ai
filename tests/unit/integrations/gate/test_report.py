"""Tests for devflow.integrations.gate.report — CheckResult, CheckDef, GateReport."""

import json

from devflow.integrations.gate.report import CheckDef, CheckResult, GateReport


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

    def test_skipped_check_does_not_fail_the_gate(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=False, skipped=True))
        assert report.passed is True
        assert report.has_skipped is True

    def test_failed_check_with_skipped_check_still_fails(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=False))
        report.add(CheckResult(name="b", passed=False, skipped=True))
        assert report.passed is False
        assert report.has_skipped is True

    def test_no_skipped_when_all_run(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=True))
        assert report.has_skipped is False

    def test_empty_report_passes(self) -> None:
        report = GateReport()
        assert report.passed is True

    def test_to_dict_roundtrip(self) -> None:
        """to_dict() output survives a JSON round-trip with correct values."""
        report = GateReport()
        report.add(CheckResult(name="ruff", passed=True, message="No issues"))
        report.add(CheckResult(name="biome", passed=False, skipped=True, message="not found"))
        d = report.to_dict()

        assert d["passed"] is True
        assert d["has_skipped"] is True
        assert len(d["checks"]) == 2

        restored = json.loads(json.dumps(d))
        assert restored["passed"] is True
        assert restored["checks"][0]["name"] == "ruff"
        assert restored["checks"][1]["skipped"] is True

    def test_to_dict_preserves_details(self) -> None:
        """Multi-line details are preserved verbatim in the dict."""
        multi = "line1\nline2\nline3"
        report = GateReport()
        report.add(CheckResult(name="ruff", passed=False, details=multi))
        assert report.to_dict()["checks"][0]["details"] == multi

    def test_add_appends_in_order(self) -> None:
        """add() preserves insertion order."""
        report = GateReport()
        names = ["ruff", "pytest", "secrets"]
        for n in names:
            report.add(CheckResult(name=n, passed=True))
        assert [c.name for c in report.checks] == names


class TestCheckDef:
    def test_defaults(self) -> None:
        """CheckDef has sensible defaults for timeout and parse_output."""
        check = CheckDef(name="x", cmd=["x"])
        assert check.timeout == 60
        assert check.parse_output is None
