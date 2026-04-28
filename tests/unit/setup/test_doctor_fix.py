"""Tests for devflow doctor --fix."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from devflow.core.gate_report import CheckResult, GateReport
from devflow.setup.doctor import _FIX_ACTIONS, _MANUAL_FIX_HINTS, run_doctor_fix


def _make_report(*checks: tuple[str, bool, str]) -> GateReport:
    """Build a GateReport from (name, passed, message) tuples."""
    report = GateReport()
    for name, passed, msg in checks:
        report.add(CheckResult(name=name, passed=passed, message=msg))
    return report


class TestRunDoctorFix:
    def test_all_green(self) -> None:
        """When everything passes, nothing to fix."""
        report = _make_report(("python", True, "3.12"), ("gh", True, "OK"))
        with patch("devflow.setup.doctor.run_doctor", return_value=report):
            result = run_doctor_fix()
        assert result.passed

    def test_manual_only(self) -> None:
        """Manual fixes are displayed but not applied."""
        report = _make_report(("gh", False, "not found"))
        with patch("devflow.setup.doctor.run_doctor", return_value=report):
            result = run_doctor_fix()
        assert not result.passed

    def test_auto_fixes_confirmed(self) -> None:
        """Auto fixes are applied when user confirms."""
        report_before = _make_report(("agents", False, "0/9 synced"))
        report_after = _make_report(("agents", True, "9/9 synced"))

        with (
            patch("devflow.setup.doctor.run_doctor", side_effect=[report_before, report_after]),
            patch("rich.prompt.Confirm.ask", return_value=True),
            patch("devflow.setup.doctor._apply_auto_fixes") as mock_apply,
        ):
            result = run_doctor_fix()
        mock_apply.assert_called_once_with(["agents"], None)
        assert result.passed

    def test_auto_fixes_declined(self) -> None:
        """Auto fixes are not applied when user declines."""
        report = _make_report(("agents", False, "0/9 synced"))
        with (
            patch("devflow.setup.doctor.run_doctor", return_value=report),
            patch("rich.prompt.Confirm.ask", return_value=False),
        ):
            result = run_doctor_fix()
        assert not result.passed

    def test_unknown_check_displayed(self) -> None:
        """Backend-specific failures are displayed with their message."""
        report = _make_report(("Claude Code", False, "cli not found"))
        with patch("devflow.setup.doctor.run_doctor", return_value=report):
            result = run_doctor_fix()
        assert not result.passed

    def test_mixed_auto_and_manual(self) -> None:
        """Both auto and manual fixes are handled."""
        report_before = _make_report(
            ("agents", False, "0/9 synced"),
            ("gh", False, "not found"),
        )
        report_after = _make_report(
            ("agents", True, "9/9 synced"),
            ("gh", False, "not found"),
        )

        with (
            patch("devflow.setup.doctor.run_doctor", side_effect=[report_before, report_after]),
            patch("rich.prompt.Confirm.ask", return_value=True),
            patch("devflow.setup.doctor._apply_auto_fixes"),
        ):
            result = run_doctor_fix()
        # gh is still failing
        assert not result.passed


class TestFixActions:
    def test_cover_known_checks(self) -> None:
        """All fixable check names are in _FIX_ACTIONS."""
        assert "agents" in _FIX_ACTIONS
        assert "skills" in _FIX_ACTIONS
        assert "hook" in _FIX_ACTIONS
        assert "init" in _FIX_ACTIONS
        assert "gh" in _FIX_ACTIONS

    def test_manual_hints_exist_for_manual_fixes(self) -> None:
        """Every manual-only fix has a hint."""
        for name, (_, action) in _FIX_ACTIONS.items():
            if action is None:
                assert name in _MANUAL_FIX_HINTS, f"Missing hint for {name}"

    def test_auto_fixes_are_auto(self) -> None:
        """Auto fixes have 'auto' or 'auto_init' as action."""
        auto_names = {"agents", "skills", "hook", "init"}
        for name in auto_names:
            _, action = _FIX_ACTIONS[name]
            assert action in ("auto", "auto_init"), f"{name} should be auto"


class TestApplyAutoFixes:
    def test_install_called_for_agents(self) -> None:
        """Install is triggered when agents need fixing."""
        from devflow.setup.doctor import _apply_auto_fixes

        mock_result = type("R", (), {
            "agents": [], "skills": [], "hook_installed": False,
        })()
        with (
            patch("devflow.setup.install.install_all", return_value=mock_result) as mock_install,
            patch("devflow.setup.install.render_install_report"),
        ):
            _apply_auto_fixes(["agents"])
        mock_install.assert_called_once()

    def test_init_called(self, tmp_path: Path) -> None:
        """Init is triggered when .devflow/ needs creation."""
        from devflow.setup.doctor import _apply_auto_fixes

        _apply_auto_fixes(["init"], base=tmp_path)
        assert (tmp_path / ".devflow" / "config.yaml").exists()
        assert (tmp_path / ".devflow" / "state.json").exists()
