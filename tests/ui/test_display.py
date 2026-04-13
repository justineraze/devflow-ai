"""Tests for devflow.ui.display — log table, log detail, format duration."""

from datetime import UTC, datetime, timedelta
from io import StringIO

from rich.console import Console

from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.ui.display import (
    _format_duration,
    render_log_detail,
    render_log_table,
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
        assert _format_duration(start, end) == "45s"

    def test_zero_seconds(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        assert _format_duration(t, t) == "0s"

    def test_minutes(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(minutes=12)
        assert _format_duration(start, end) == "12m"

    def test_hours_and_minutes(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=2, minutes=15)
        assert _format_duration(start, end) == "2h 15m"

    def test_exact_hours(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=3)
        assert _format_duration(start, end) == "3h"

    def test_days_and_hours(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=3, hours=4)
        assert _format_duration(start, end) == "3d 4h"

    def test_exact_days(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=5)
        assert _format_duration(start, end) == "5d"


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
