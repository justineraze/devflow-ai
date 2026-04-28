"""KPI computation from v2 metrics records.

All calculations are done at read time — nothing precomputed or stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median

from devflow.core.history import MetricsRecord


@dataclass
class MetricsDashboard:
    """Computed KPIs from metrics history."""

    top_features_by_cost: list[tuple[str, float]] = field(default_factory=list)
    gate_first_try_rate: float = 0.0
    time_to_pr_median_s: float = 0.0
    time_to_pr_p90_s: float = 0.0
    cache_hit_rate: float = 0.0
    cost_by_backend: dict[str, float] = field(default_factory=dict)
    total_cost: float = 0.0
    total_features: int = 0
    budget_warnings: list[tuple[str, float, float]] = field(default_factory=list)


def compute_dashboard(
    records: list[MetricsRecord],
    since: datetime | None = None,
    budget_per_feature: float | None = None,
) -> MetricsDashboard:
    """Compute all KPIs from flat v2 records."""
    if since:
        records = [r for r in records if _parse_ts(r.ts_start) >= since]

    if not records:
        return MetricsDashboard()

    # Group by feature.
    by_feature: dict[str, list[MetricsRecord]] = {}
    for r in records:
        by_feature.setdefault(r.feature_id, []).append(r)

    # 1. Cost per feature — top 5.
    feature_costs = {
        fid: sum(r.cost_usd for r in recs)
        for fid, recs in by_feature.items()
    }
    top_features = sorted(feature_costs.items(), key=lambda x: -x[1])[:5]

    # 2. Gate-passed-first-try rate.
    features_with_gate = 0
    features_gate_first = 0
    for _fid, recs in by_feature.items():
        gate_recs = [r for r in recs if r.phase == "gate"]
        if gate_recs:
            features_with_gate += 1
            if gate_recs[0].outcome == "success":
                features_gate_first += 1
    gate_rate = features_gate_first / features_with_gate if features_with_gate else 0.0

    # 3. Time-to-PR — from first ts_start to last ts_end per feature.
    durations: list[float] = []
    for recs in by_feature.values():
        starts = [_parse_ts(r.ts_start) for r in recs if r.ts_start]
        ends = [_parse_ts(r.ts_end) for r in recs if r.ts_end]
        if starts and ends:
            total_s = (max(ends) - min(starts)).total_seconds()
            if total_s > 0:
                durations.append(total_s)

    time_median = median(durations) if durations else 0.0
    time_p90 = _percentile(durations, 90) if durations else 0.0

    # 4. Cache hit rate.
    total_cache_read = sum(r.cache_read for r in records)
    total_tokens_in = sum(r.tokens_in + r.cache_creation + r.cache_read for r in records)
    cache_rate = total_cache_read / total_tokens_in if total_tokens_in > 0 else 0.0

    # 5. Cost by backend.
    cost_by_backend: dict[str, float] = {}
    for r in records:
        cost_by_backend[r.backend] = cost_by_backend.get(r.backend, 0.0) + r.cost_usd

    total_cost = sum(r.cost_usd for r in records)

    # Budget warnings.
    warnings: list[tuple[str, float, float]] = []
    if budget_per_feature is not None and budget_per_feature > 0:
        for fid, cost in feature_costs.items():
            if cost > budget_per_feature:
                warnings.append((fid, cost, budget_per_feature))

    return MetricsDashboard(
        top_features_by_cost=top_features,
        gate_first_try_rate=gate_rate,
        time_to_pr_median_s=time_median,
        time_to_pr_p90_s=time_p90,
        cache_hit_rate=cache_rate,
        cost_by_backend=cost_by_backend,
        total_cost=total_cost,
        total_features=len(by_feature),
        budget_warnings=warnings,
    )


def parse_since(value: str) -> datetime:
    """Parse a --since value like '7d' or '2w' into a UTC datetime."""
    value = value.strip().lower()
    if value.endswith("d"):
        days = int(value[:-1])
        return datetime.now(UTC) - timedelta(days=days)
    if value.endswith("w"):
        weeks = int(value[:-1])
        return datetime.now(UTC) - timedelta(weeks=weeks)
    msg = f"Invalid --since format: {value!r} (expected Nd or Nw)"
    raise ValueError(msg)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp, falling back to epoch on failure."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return datetime(2000, 1, 1, tzinfo=UTC)


def _percentile(data: list[float], pct: int) -> float:
    """Compute the *pct*-th percentile (simple nearest-rank)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = max(0, min(len(sorted_data) - 1, int(len(sorted_data) * pct / 100)))
    return sorted_data[idx]
