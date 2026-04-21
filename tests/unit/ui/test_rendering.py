"""Smoke tests for the build-flow Rich renderers."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.orchestration.stream import PhaseMetrics
from devflow.ui import rendering as r


def _capture(fn, *args, **kwargs) -> str:
    """Render *fn* into a string console and return the captured output."""
    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=False, no_color=True)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(r, "console", console)
    try:
        fn(*args, **kwargs)
    finally:
        monkey.undo()
    return buf.getvalue()


def _feature() -> Feature:
    return Feature(
        id="feat-001",
        description="Add caching layer",
        workflow="standard",
        status=FeatureStatus.DONE,
        phases=[
            PhaseRecord(name="planning", status=PhaseStatus.DONE),
            PhaseRecord(name="implementing", status=PhaseStatus.DONE),
            PhaseRecord(name="reviewing", status=PhaseStatus.DONE),
            PhaseRecord(name="gate", status=PhaseStatus.DONE),
        ],
    )


class TestBanner:
    def test_includes_description_and_metadata(self) -> None:
        out = _capture(r.render_build_banner, _feature(), "feat/feat-001", "python")
        assert "Add caching layer" in out
        assert "feat-001" in out
        assert "🐍" in out
        assert "python" in out
        assert "standard" in out
        assert "4 phases" in out
        assert "feat/feat-001" in out

    def test_unknown_stack_falls_back_to_generic(self) -> None:
        out = _capture(r.render_build_banner, _feature(), "feat/x", None)
        assert "generic" in out


class TestPhaseHeader:
    def test_shows_position_name_and_model(self) -> None:
        out = _capture(r.render_phase_header, 2, 4, "implementing", "sonnet")
        assert "phase 2/4" in out
        assert "implementing" in out
        assert "sonnet" in out


class TestPhaseSuccess:
    def test_renders_metrics_chip(self) -> None:
        m = PhaseMetrics(
            input_tokens=5200, output_tokens=1800, cache_read=18000,
            cost_usd=0.18, tool_count=8,
        )
        out = _capture(r.render_phase_success, "implementing", 154, m)
        assert "✓" in out
        assert "implementing" in out
        assert "2m34s" in out
        assert "8 tools" in out
        # Total input = 5200 + 18000 = 23200 → "23.2k"
        assert "23.2k" in out
        assert "cached" in out
        assert "$0.18" in out

    def test_no_metrics_skips_token_section(self) -> None:
        out = _capture(r.render_phase_success, "gate", 1, PhaseMetrics())
        assert "✓" in out
        assert "gate" in out
        assert "$" not in out


class TestPhaseFailure:
    def test_renders_failure_with_message_lines(self) -> None:
        out = _capture(
            r.render_phase_failure, "implementing", 12, "boom\ntraceback\n…"
        )
        assert "✗" in out
        assert "implementing" in out
        assert "boom" in out


class TestPhaseAutoRetry:
    def test_yellow_retry_message(self) -> None:
        out = _capture(r.render_phase_auto_retry, "gate", 5, "")
        assert "↻" in out
        assert "gate failed" in out
        assert "auto-retrying" in out


class TestBuildSummary:
    def _totals(self) -> r.BuildTotals:
        t = r.BuildTotals()
        t.add("planning", PhaseMetrics(
            input_tokens=2400, output_tokens=900,
            cache_read=12000, cost_usd=0.12, tool_count=3,
        ), 72)
        t.add("implementing", PhaseMetrics(
            input_tokens=5200, output_tokens=1800,
            cache_read=18000, cost_usd=0.18, tool_count=8,
        ), 154)
        t.add("reviewing", PhaseMetrics(
            input_tokens=3100, output_tokens=620,
            cache_read=22000, cost_usd=0.21, tool_count=4,
        ), 48)
        t.add("gate", PhaseMetrics(), 1)
        return t

    def test_includes_totals_and_pr_url(self) -> None:
        out = _capture(
            r.render_build_summary,
            _feature(), self._totals(),
            "https://github.com/x/y/pull/1", "feat/feat-001",
        )
        assert "Build complete" in out
        assert "Duration" in out
        assert "Cost" in out
        assert "Tokens" in out
        assert "Cache" in out
        assert "https://github.com/x/y/pull/1" in out
        assert "planning" in out
        assert "gate" in out

    def test_falls_back_to_branch_when_no_pr(self) -> None:
        out = _capture(
            r.render_build_summary,
            _feature(), self._totals(), None, "feat/feat-001",
        )
        assert "feat/feat-001" in out
        assert "https://" not in out

    def test_cost_budget_renders_bar(self) -> None:
        out = _capture(
            r.render_build_summary,
            _feature(), self._totals(),
            None, "feat/x", cost_budget=2.0,
        )
        assert "Cost" in out
        assert "$2.00" in out


class TestFmtDuration:
    @pytest.mark.parametrize("seconds,expected", [
        (None, "—"),
        (0.5, "500ms"),
        (1, "1s"),
        (48, "48s"),
        (60, "1m00s"),
        (154, "2m34s"),
        (3661, "61m01s"),
    ])
    def test_format(self, seconds: float | None, expected: str) -> None:
        assert r._fmt_duration(seconds) == expected
