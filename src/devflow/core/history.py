"""Build metrics history — append-only JSONL persistence.

Stores one record per completed (or failed) build in ``.devflow/metrics.jsonl``.
Append-only format ensures crash-safety (no read-modify-write cycle)
and makes diffs easy to review.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devflow.core.models import Feature
    from devflow.ui.rendering import BuildTotals


@dataclass
class PhaseSnapshot:
    """Metrics snapshot for a single phase execution."""

    name: str
    model: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    tool_count: int = 0
    duration_s: float = 0.0
    success: bool = True


@dataclass
class BuildMetrics:
    """Single build execution record — success or failure."""

    feature_id: str
    description: str
    workflow: str
    timestamp: str
    success: bool = True
    failed_phase: str | None = None
    # Totals
    duration_s: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    tool_count: int = 0
    # Quality signals
    gate_passed_first_try: bool = False
    gate_retries: int = 0
    phases_total: int = 0
    phases_completed: int = 0
    # Per-phase breakdown (full detail for dashboard/analysis)
    phases: list[PhaseSnapshot] = field(default_factory=list)

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0.0-1.0)."""
        total = self.input_tokens + self.cache_read
        return self.cache_read / total if total > 0 else 0.0

    @property
    def phase_costs(self) -> dict[str, float]:
        """Cost breakdown by phase name (for backwards compat)."""
        return {p.name: p.cost_usd for p in self.phases if p.cost_usd}

    @property
    def phase_durations(self) -> dict[str, float]:
        """Duration breakdown by phase name."""
        return {p.name: p.duration_s for p in self.phases}


def _metrics_path(base: Path | None = None) -> Path:
    """Return the path to the metrics JSONL file."""
    from devflow.core.workflow import ensure_devflow_dir

    return ensure_devflow_dir(base) / "metrics.jsonl"


def build_metrics_from(
    feature: Feature, totals: BuildTotals, success: bool,
) -> BuildMetrics:
    """Construct a BuildMetrics from a build's feature and totals."""
    from devflow.core.models import PhaseStatus

    phases_completed = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
    gate_passed_first = feature.metadata.gate_retry == 0 and success

    # Determine which phase failed (if any).
    failed_phase: str | None = None
    if not success:
        for snap in reversed(totals.phase_snapshots):
            if not snap.success:
                failed_phase = snap.name
                break

    # Build per-phase records from snapshots.
    phase_records = [
        PhaseSnapshot(
            name=s.name,
            model=s.model,
            cost_usd=round(s.cost_usd, 4),
            input_tokens=s.input_tokens,
            output_tokens=s.output_tokens,
            cache_read=s.cache_read,
            tool_count=s.tool_count,
            duration_s=round(s.duration_s, 1),
            success=s.success,
        )
        for s in totals.phase_snapshots
    ]

    return BuildMetrics(
        feature_id=feature.id,
        description=feature.description,
        workflow=feature.workflow,
        timestamp=datetime.now(UTC).isoformat(),
        success=success,
        failed_phase=failed_phase,
        duration_s=round(totals.duration_s, 1),
        cost_usd=round(totals.cost_usd, 4),
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_read=totals.cache_read,
        tool_count=totals.tool_count,
        gate_passed_first_try=gate_passed_first,
        gate_retries=feature.metadata.gate_retry,
        phases_total=len(feature.phases),
        phases_completed=phases_completed,
        phases=phase_records,
    )


def append_build_metrics(record: BuildMetrics, base: Path | None = None) -> None:
    """Append a build record to the metrics JSONL file."""
    path = _metrics_path(base)
    line = json.dumps(asdict(record), separators=(",", ":"))
    with path.open("a") as f:
        f.write(line + "\n")


def read_history(base: Path | None = None, limit: int = 50) -> list[BuildMetrics]:
    """Read the last *limit* build records, most recent first."""
    path = _metrics_path(base)
    if not path.exists():
        return []

    records: list[BuildMetrics] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            # Deserialize nested PhaseSnapshot list.
            raw_phases = data.pop("phases", [])
            rec = BuildMetrics(**data)
            rec.phases = [PhaseSnapshot(**p) for p in raw_phases]
            records.append(rec)
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    return list(reversed(records[-limit:]))
