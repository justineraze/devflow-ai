"""Tests for devflow.core.kpis — KPI computation from metrics records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from devflow.core.history import MetricsRecord
from devflow.core.kpis import compute_dashboard, parse_since


def _record(
    feature_id: str = "feat-1",
    phase: str = "implementing",
    cost_usd: float = 0.10,
    backend: str = "claude",
    ts_start: str = "2026-04-20T10:00:00+00:00",
    ts_end: str = "2026-04-20T10:05:00+00:00",
    duration_s: float = 300.0,
    tokens_in: int = 1000,
    cache_read: int = 500,
    cache_creation: int = 200,
    outcome: str = "success",
    model: str = "sonnet",
    **kwargs: object,
) -> MetricsRecord:
    return MetricsRecord(
        feature_id=feature_id,
        phase=phase,
        cost_usd=cost_usd,
        backend=backend,
        ts_start=ts_start,
        ts_end=ts_end,
        duration_s=duration_s,
        tokens_in=tokens_in,
        cache_read=cache_read,
        cache_creation=cache_creation,
        outcome=outcome,
        model=model,
        **kwargs,  # type: ignore[arg-type]
    )


class TestCostPerFeature:
    def test_top_features_sorted_by_cost(self) -> None:
        records = [
            _record(feature_id="feat-1", cost_usd=0.50),
            _record(feature_id="feat-1", cost_usd=0.30),
            _record(feature_id="feat-2", cost_usd=1.00),
            _record(feature_id="feat-3", cost_usd=0.20),
        ]
        d = compute_dashboard(records)
        assert d.top_features_by_cost[0] == ("feat-2", 1.00)
        assert d.top_features_by_cost[1] == ("feat-1", 0.80)
        assert d.top_features_by_cost[2] == ("feat-3", 0.20)

    def test_top_features_capped_at_5(self) -> None:
        records = [
            _record(feature_id=f"feat-{i}", cost_usd=float(i))
            for i in range(10)
        ]
        d = compute_dashboard(records)
        assert len(d.top_features_by_cost) == 5


class TestGateFirstTryRate:
    def test_mixed_success_failure(self) -> None:
        records = [
            _record(feature_id="f1", phase="gate", outcome="success"),
            _record(feature_id="f2", phase="gate", outcome="failure"),
            _record(feature_id="f2", phase="gate", outcome="success"),
            _record(feature_id="f3", phase="gate", outcome="success"),
        ]
        d = compute_dashboard(records)
        # f1: first gate=success, f2: first gate=failure, f3: first gate=success
        assert d.gate_first_try_rate == pytest.approx(2 / 3)

    def test_no_gate_phases(self) -> None:
        records = [_record(phase="implementing")]
        d = compute_dashboard(records)
        assert d.gate_first_try_rate == 0.0


class TestTimeToPR:
    def test_median_and_p90(self) -> None:
        records = []
        for i in range(5):
            dur = (i + 1) * 60
            start = "2026-04-20T10:00:00+00:00"
            end_dt = datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=dur)
            records.append(_record(
                feature_id=f"feat-{i}",
                ts_start=start,
                ts_end=end_dt.isoformat(),
            ))
        d = compute_dashboard(records)
        assert d.time_to_pr_median_s > 0
        assert d.time_to_pr_p90_s >= d.time_to_pr_median_s


class TestCacheHitRate:
    def test_correct_calculation(self) -> None:
        records = [
            _record(tokens_in=200, cache_read=800, cache_creation=0),
        ]
        d = compute_dashboard(records)
        # 800 / (200 + 0 + 800) = 0.8
        assert d.cache_hit_rate == pytest.approx(0.8)

    def test_zero_tokens(self) -> None:
        records = [_record(tokens_in=0, cache_read=0, cache_creation=0)]
        d = compute_dashboard(records)
        assert d.cache_hit_rate == 0.0


class TestCostByBackend:
    def test_claude_and_pi(self) -> None:
        records = [
            _record(backend="claude", cost_usd=1.00),
            _record(backend="claude", cost_usd=0.50),
            _record(backend="pi", cost_usd=0.30),
        ]
        d = compute_dashboard(records)
        assert d.cost_by_backend["claude"] == pytest.approx(1.50)
        assert d.cost_by_backend["pi"] == pytest.approx(0.30)


class TestDashboardEmpty:
    def test_empty_records(self) -> None:
        d = compute_dashboard([])
        assert d.total_features == 0
        assert d.total_cost == 0.0
        assert d.top_features_by_cost == []
        assert d.gate_first_try_rate == 0.0
        assert d.time_to_pr_median_s == 0.0


class TestSinceFilter:
    def test_records_filtered_by_since(self) -> None:
        old = _record(
            feature_id="old",
            ts_start="2026-01-01T10:00:00+00:00",
        )
        recent = _record(
            feature_id="recent",
            ts_start=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )
        since = datetime.now(UTC) - timedelta(days=7)
        d = compute_dashboard([old, recent], since=since)
        assert d.total_features == 1
        assert d.top_features_by_cost[0][0] == "recent"


class TestBudgetWarnings:
    def test_feature_above_threshold(self) -> None:
        records = [
            _record(feature_id="feat-1", cost_usd=0.60),
            _record(feature_id="feat-2", cost_usd=0.30),
        ]
        d = compute_dashboard(records, budget_per_feature=0.50)
        assert len(d.budget_warnings) == 1
        assert d.budget_warnings[0][0] == "feat-1"


class TestParseSince:
    def test_days(self) -> None:
        dt = parse_since("7d")
        expected = datetime.now(UTC) - timedelta(days=7)
        assert abs((dt - expected).total_seconds()) < 2

    def test_weeks(self) -> None:
        dt = parse_since("2w")
        expected = datetime.now(UTC) - timedelta(weeks=2)
        assert abs((dt - expected).total_seconds()) < 2

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid --since"):
            parse_since("7h")
