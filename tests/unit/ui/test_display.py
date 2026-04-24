"""Tests for devflow.ui.display — log table, log detail, format duration, metrics."""

from datetime import UTC, datetime, timedelta
from io import StringIO

from rich.console import Console

from devflow.core.history import BuildMetrics, PhaseSnapshot
from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.ui.display import (
    _format_elapsed,
    render_log_detail,
    render_log_table,
    render_metrics_table,
)


def _make_feature(
    feature_id: str = "feat-001",
    status: FeatureStatus = FeatureStatus.DONE,
    workflow: str = "standard",
    description: str = "Test feature",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    phases: list[PhaseRecord] | None = None,
) -> Feature:
    """Helper to build a Feature with sensible defaults."""
    now = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
    return Feature(
        id=feature_id,
        description=description,
        status=status,
        workflow=workflow,
        created_at=created_at or now,
        updated_at=updated_at or now + timedelta(hours=2, minutes=15),
        phases=phases or [],
    )


def _capture(func, *args) -> str:  # noqa: ANN001
    """Capture Rich console output from a display function."""
    import devflow.ui.display as display_mod

    original = display_mod.console
    buf = StringIO()
    display_mod.console = Console(file=buf, force_terminal=False, width=120, no_color=True)
    try:
        func(*args)
    finally:
        display_mod.console = original
    return buf.getvalue()


class TestFormatDuration:
    def test_seconds(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(seconds=45)
        assert _format_elapsed(start, end) == "45s"

    def test_zero_seconds(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        assert _format_elapsed(t, t) == "0s"

    def test_minutes(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(minutes=12)
        assert _format_elapsed(start, end) == "12m"

    def test_hours_and_minutes(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=2, minutes=15)
        assert _format_elapsed(start, end) == "2h 15m"

    def test_exact_hours(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=3)
        assert _format_elapsed(start, end) == "3h"

    def test_days_and_hours(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=3, hours=4)
        assert _format_elapsed(start, end) == "3d 4h"

    def test_exact_days(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=5)
        assert _format_elapsed(start, end) == "5d"


class TestRenderLogTable:
    def test_empty_list(self) -> None:
        output = _capture(render_log_table, [])
        assert "No features in history" in output

    def test_with_features(self) -> None:
        features = [
            _make_feature("feat-001", FeatureStatus.DONE, phases=[
                PhaseRecord(name="planning", status=PhaseStatus.DONE),
                PhaseRecord(name="implementing", status=PhaseStatus.DONE),
            ]),
            _make_feature(
                "feat-002",
                FeatureStatus.IMPLEMENTING,
                created_at=datetime(2026, 4, 11, 8, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 11, 9, 30, 0, tzinfo=UTC),
                phases=[
                    PhaseRecord(name="planning", status=PhaseStatus.DONE),
                    PhaseRecord(name="implementing", status=PhaseStatus.IN_PROGRESS),
                    PhaseRecord(name="reviewing", status=PhaseStatus.PENDING),
                ],
            ),
        ]
        output = _capture(render_log_table, features)
        assert "feat-001" in output
        assert "feat-002" in output
        assert "2/2" in output  # feat-001 phases
        assert "1/3" in output  # feat-002 phases
        assert "done" in output
        assert "implementing" in output

    def test_sorted_by_date_descending(self) -> None:
        older = _make_feature(
            "feat-old",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        )
        newer = _make_feature(
            "feat-new",
            created_at=datetime(2026, 4, 12, tzinfo=UTC),
            updated_at=datetime(2026, 4, 12, 1, 0, tzinfo=UTC),
        )
        output = _capture(render_log_table, [older, newer])
        pos_new = output.index("feat-new")
        pos_old = output.index("feat-old")
        assert pos_new < pos_old


class TestRenderLogDetail:
    def test_with_phases(self) -> None:
        start = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        feature = _make_feature(
            "feat-001",
            description="Add log command",
            phases=[
                PhaseRecord(
                    name="planning",
                    status=PhaseStatus.DONE,
                    started_at=start,
                    completed_at=start + timedelta(minutes=5),
                ),
                PhaseRecord(
                    name="implementing",
                    status=PhaseStatus.IN_PROGRESS,
                    started_at=start + timedelta(minutes=5),
                ),
            ],
        )
        output = _capture(render_log_detail, feature)
        assert "feat-001" in output
        assert "Add log command" in output
        assert "planning" in output
        assert "implementing" in output
        assert "5m" in output  # planning duration
        assert "—" in output  # implementing has no completed_at

    def test_with_errors(self) -> None:
        start = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        feature = _make_feature(
            "feat-err",
            status=FeatureStatus.FAILED,
            phases=[
                PhaseRecord(
                    name="gate",
                    status=PhaseStatus.FAILED,
                    started_at=start,
                    completed_at=start + timedelta(minutes=1),
                    error="ruff found 3 issues",
                ),
            ],
        )
        output = _capture(render_log_detail, feature)
        assert "ruff found 3 issues" in output
        assert "failed" in output

    def test_no_phases(self) -> None:
        feature = _make_feature("feat-empty", phases=[])
        output = _capture(render_log_detail, feature)
        assert "No phases recorded" in output


def _make_build_metrics(
    feature_id: str = "feat-001",
    success: bool = True,
    cost_usd: float = 0.05,
    phases: list[PhaseSnapshot] | None = None,
) -> BuildMetrics:
    """Helper to build a BuildMetrics with sensible defaults."""
    if phases is None:
        phases = [
            PhaseSnapshot(
                name="planning",
                model="claude-sonnet-4-5",
                cost_usd=0.02,
                input_tokens=5000,
                cache_creation=40000,
                cache_read=3000,
                duration_s=45.0,
                success=True,
            ),
            PhaseSnapshot(
                name="implementing",
                model="claude-sonnet-4-5",
                cost_usd=0.03,
                input_tokens=8000,
                cache_creation=5000,
                cache_read=6000,
                duration_s=90.0,
                success=True,
            ),
        ]
    record = BuildMetrics(
        feature_id=feature_id,
        description=f"Test feature {feature_id}",
        workflow="light",
        timestamp="2026-04-21T10:00:00+00:00",
        success=success,
        cost_usd=cost_usd,
        input_tokens=sum(p.input_tokens for p in phases),
        cache_creation=sum(p.cache_creation for p in phases),
        cache_read=sum(p.cache_read for p in phases),
        duration_s=sum(p.duration_s for p in phases),
        gate_passed_first_try=success,
        phases=phases,
    )
    return record


class TestRenderMetricsTable:
    def test_empty_list(self) -> None:
        output = _capture(render_metrics_table, [])
        assert "No build history" in output

    def test_single_build_shows_last_build_and_history(self) -> None:
        record = _make_build_metrics("feat-metrics-001")
        output = _capture(render_metrics_table, [record])
        # Last build panel present
        assert "Last build" in output
        assert "feat-metrics-001" in output
        # Phase breakdown present
        assert "planning" in output
        assert "implementing" in output
        # History table present
        assert "Build history" in output
        # No phase averages with only 1 record
        assert "Avg cost by phase" not in output

    def test_multiple_builds_show_all_three_sections(self) -> None:
        records = [
            _make_build_metrics("feat-001", cost_usd=0.05),
            _make_build_metrics("feat-002", cost_usd=0.08),
            _make_build_metrics("feat-003", cost_usd=0.03),
        ]
        output = _capture(render_metrics_table, records)
        # All 3 sections
        assert "Last build" in output
        assert "Avg cost by phase" in output
        assert "Build history" in output
        # Most recent is records[0]
        assert "feat-001" in output
        assert "planning" in output

    def test_zero_cost_phases_appear_in_averages(self) -> None:
        phases = [
            PhaseSnapshot(name="gate", cost_usd=0.0, duration_s=5.0, success=True),
            PhaseSnapshot(name="implementing", cost_usd=0.04, duration_s=60.0, success=True),
        ]
        records = [
            _make_build_metrics("feat-a", phases=phases, cost_usd=0.04),
            _make_build_metrics("feat-b", phases=phases, cost_usd=0.04),
        ]
        output = _capture(render_metrics_table, records)
        assert "Avg cost by phase" in output
        # Both phases should appear even though gate has $0.00
        assert "gate" in output
        assert "implementing" in output

    def test_phase_averages_include_cache_percent(self) -> None:
        phases = [
            PhaseSnapshot(
                name="planning", model="opus", cost_usd=0.05,
                input_tokens=2000, cache_creation=3000, cache_read=15000,
                duration_s=30.0, success=True,
            ),
        ]
        records = [
            _make_build_metrics("feat-c1", phases=phases, cost_usd=0.05),
            _make_build_metrics("feat-c2", phases=phases, cost_usd=0.05),
        ]
        output = _capture(render_metrics_table, records)
        assert "Cache %" in output
        # 15000 / (2000+3000+15000) = 75%
        assert "75%" in output

    def test_build_history_models_column_shows_cost(self) -> None:
        phases = [
            PhaseSnapshot(
                name="planning", model="opus", cost_usd=0.12,
                input_tokens=5000, cache_creation=3000, cache_read=2000,
                duration_s=30.0, success=True,
            ),
            PhaseSnapshot(
                name="implementing", model="sonnet", cost_usd=0.04,
                input_tokens=4000, cache_creation=1000, cache_read=1000,
                duration_s=60.0, success=True,
            ),
        ]
        records = [_make_build_metrics("feat-m1", phases=phases, cost_usd=0.16)]
        output = _capture(render_metrics_table, records)
        # Models column now shows cost per model (may wrap across lines).
        assert "opus $0.12" in output
        assert "$0.04" in output
