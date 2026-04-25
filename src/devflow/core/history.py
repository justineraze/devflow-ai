"""Build metrics history — append-only JSONL persistence.

Stores one record per completed (or failed) build in ``.devflow/metrics.jsonl``.
Append-only format ensures crash-safety (no read-modify-write cycle)
and makes diffs easy to review.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from devflow.core.metrics import BuildTotals, PhaseSnapshot, compute_cache_hit_rate
from devflow.core.models import PhaseStatus
from devflow.core.workflow import ensure_devflow_dir

if TYPE_CHECKING:
    from devflow.core.models import Feature

__all__ = [
    "BuildMetrics",
    "append_build_metrics",
    "build_metrics_from",
    "read_history",
]


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
    cache_creation: int = 0
    cache_read: int = 0
    tool_count: int = 0
    # Quality signals
    gate_passed_first_try: bool = False
    gate_retries: int = 0
    phases_total: int = 0
    phases_completed: int = 0
    # Commit stats
    commits_count: int = 0
    commits_by_phase: dict[str, int] = field(default_factory=dict)
    # Scoring method used for workflow selection (e.g. "llm", "heuristic").
    scorer_method: str = ""
    # Per-phase breakdown (full detail for dashboard/analysis)
    phases: list[PhaseSnapshot] = field(default_factory=list)

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0.0-1.0)."""
        return compute_cache_hit_rate(self.input_tokens, self.cache_creation, self.cache_read)

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
    return ensure_devflow_dir(base) / "metrics.jsonl"


def build_metrics_from(
    feature: Feature, totals: BuildTotals, success: bool,
) -> BuildMetrics:
    """Construct a BuildMetrics from a build's feature and totals."""
    phases_completed = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
    # gate_passed_first means no retry was needed (gate succeeded on first attempt)
    gate_passed_first = feature.metadata.gate_retry == 0 and success

    # Determine which phase failed (if any).
    failed_phase: str | None = None
    if not success:
        for snap in reversed(totals.phase_snapshots):
            if not snap.success:
                failed_phase = snap.name
                break

    # Round float fields for cleaner JSONL output; snapshots are already
    # PhaseSnapshot instances so we just copy with rounding.
    phase_records = [
        PhaseSnapshot(
            name=s.name, model=s.model,
            cost_usd=round(s.cost_usd, 4),
            input_tokens=s.input_tokens, output_tokens=s.output_tokens,
            cache_creation=s.cache_creation, cache_read=s.cache_read,
            tool_count=s.tool_count, duration_s=round(s.duration_s, 1),
            success=s.success, commits=s.commits,
            files_changed=s.files_changed,
            insertions=s.insertions, deletions=s.deletions,
        )
        for s in totals.phase_snapshots
    ]

    # Aggregate commit stats across phases.
    total_commits = sum(s.commits for s in totals.phase_snapshots)
    commits_by_phase = {
        s.name: s.commits for s in totals.phase_snapshots if s.commits > 0
    }

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
        cache_creation=totals.cache_creation,
        cache_read=totals.cache_read,
        tool_count=totals.tool_count,
        gate_passed_first_try=gate_passed_first,
        gate_retries=feature.metadata.gate_retry,
        phases_total=len(feature.phases),
        phases_completed=phases_completed,
        commits_count=total_commits,
        commits_by_phase=commits_by_phase,
        scorer_method=(
            feature.metadata.complexity.method
            if feature.metadata.complexity is not None
            else ""
        ),
        phases=phase_records,
    )


def append_build_metrics(record: BuildMetrics, base: Path | None = None) -> None:
    """Append a build record to the metrics JSONL file."""
    path = _metrics_path(base)
    line = json.dumps(asdict(record), separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_history(base: Path | None = None, limit: int = 50) -> list[BuildMetrics]:
    """Read the last *limit* build records, most recent first.

    Uses a bounded deque so memory is O(limit) regardless of how many
    historical records the JSONL file contains — the previous version
    parsed the whole file just to slice the tail off, which got slower
    with every successful build.
    """
    path = _metrics_path(base)
    if not path.exists():
        return []
    if limit <= 0:
        return []

    # Known fields for forward-compatible deserialization: ignore any
    # fields added in newer versions that this code doesn't know about.
    _build_fields = {f.name for f in fields(BuildMetrics)}
    _phase_fields = {f.name for f in fields(PhaseSnapshot)}

    tail: deque[BuildMetrics] = deque(maxlen=limit)
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                raw_phases = data.pop("phases", [])
                known_data = {k: v for k, v in data.items() if k in _build_fields}
                rec = BuildMetrics(**known_data)
                rec.phases = [
                    PhaseSnapshot(**{k: v for k, v in p.items() if k in _phase_fields})
                    for p in raw_phases
                ]
                tail.append(rec)
            except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                continue

    # Most-recent-first.
    return list(reversed(tail))
