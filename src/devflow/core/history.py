"""Build metrics history — append-only JSONL persistence.

Stores records in ``.devflow/metrics.jsonl``.

**v1 format** (legacy): one record per build with nested ``phases[]``.
**v2 format** (current): one flat record per phase — written as each phase
completes. v1 records are migrated transparently on read.

Append-only format ensures crash-safety (no read-modify-write cycle)
and makes diffs easy to review.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from devflow.core.metrics import BuildTotals, PhaseSnapshot, compute_cache_hit_rate
from devflow.core.models import PhaseStatus
from devflow.core.workflow import ensure_devflow_dir

log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from devflow.core.models import Feature

__all__ = [
    "BuildMetrics",
    "MetricsRecord",
    "append_build_metrics",
    "append_phase_metrics",
    "build_metrics_from",
    "read_history",
    "read_phase_records",
]


# ── v2 flat record ───────────────────────────────────────────────────


@dataclass
class MetricsRecord:
    """Single v2 flat record — one per phase execution."""

    version: int = 2
    feature_id: str = ""
    description: str = ""
    workflow: str = ""
    phase: str = ""
    backend: str = "claude"
    ts_start: str = ""
    ts_end: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    model: str = ""
    outcome: str = "success"


# ── v1 build record (kept for backward compat) ──────────────────────


@dataclass
class BuildMetrics:
    """Single build execution record — success or failure (v1 schema)."""

    feature_id: str
    description: str
    workflow: str
    timestamp: str
    version: int = 1
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


# ── Writers ──────────────────────────────────────────────────────────


def append_build_metrics(record: BuildMetrics, base: Path | None = None) -> None:
    """Append a v1 build record to the metrics JSONL file."""
    path = _metrics_path(base)
    line = json.dumps(asdict(record), separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def append_phase_metrics(
    *,
    feature_id: str,
    description: str,
    workflow: str,
    phase: str,
    backend: str,
    ts_start: str,
    ts_end: str,
    duration_s: float,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
    cache_read: int,
    cache_creation: int,
    model: str,
    outcome: str,
    base: Path | None = None,
) -> None:
    """Append a v2 flat per-phase record to the metrics JSONL file."""
    record = {
        "version": 2,
        "feature_id": feature_id,
        "description": description,
        "workflow": workflow,
        "phase": phase,
        "backend": backend,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "duration_s": round(duration_s, 1),
        "cost_usd": round(cost_usd, 4),
        "tokens": {
            "in": tokens_in,
            "out": tokens_out,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        },
        "model": model,
        "outcome": outcome,
    }
    path = _metrics_path(base)
    line = json.dumps(record, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Readers ──────────────────────────────────────────────────────────


def read_phase_records(
    base: Path | None = None, limit: int = 500,
) -> list[MetricsRecord]:
    """Read metrics as flat v2 records (one per phase), most recent first.

    v1 records are migrated transparently: a single v1 line with nested
    phases produces N MetricsRecord entries.
    """
    path = _metrics_path(base)
    if not path.exists():
        return []
    if limit <= 0:
        return []

    _record_fields = {f.name for f in fields(MetricsRecord)}
    tail: deque[MetricsRecord] = deque(maxlen=limit)

    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                data_version = data.get("version", 1)

                if data_version < 2:
                    from devflow.core.migrations import METRICS_VERSION, migrate_metrics_line
                    v2_records = migrate_metrics_line(data, data_version, METRICS_VERSION)
                else:
                    v2_records = [data]

                for rec_data in v2_records:
                    tail.append(_parse_v2_record(rec_data, _record_fields))
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                log.warning(
                    "metrics.jsonl line %d skipped (%s): %s",
                    line_no, type(exc).__name__, exc,
                )
                continue

    return list(reversed(tail))


def _parse_v2_record(data: dict[str, Any], known_fields: set[str]) -> MetricsRecord:
    """Parse a v2 JSON dict into a MetricsRecord."""
    tokens = data.get("tokens", {})
    if isinstance(tokens, dict):
        data["tokens_in"] = int(tokens.get("in", 0))
        data["tokens_out"] = int(tokens.get("out", 0))
        data["cache_read"] = int(tokens.get("cache_read", 0))
        data["cache_creation"] = int(tokens.get("cache_creation", 0))
    data.pop("tokens", None)
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return MetricsRecord(**filtered)


def read_history(base: Path | None = None, limit: int = 50) -> list[BuildMetrics]:
    """Read the last *limit* build records, most recent first.

    Handles both v1 (nested phases) and v2 (flat per-phase) formats.
    v2 records are grouped by feature_id to reconstruct BuildMetrics.
    """
    path = _metrics_path(base)
    if not path.exists():
        return []
    if limit <= 0:
        return []

    _build_fields = {f.name for f in fields(BuildMetrics)}
    _phase_fields = {f.name for f in fields(PhaseSnapshot)}

    # We collect both v1 BuildMetrics and v2 flat records, then merge.
    v1_records: list[BuildMetrics] = []
    # v2 records grouped by feature_id, preserving order.
    v2_groups: dict[str, list[dict[str, Any]]] = {}

    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                data_version = data.get("version", 1)

                if data_version >= 2 and "phase" in data:
                    fid = str(data.get("feature_id", ""))
                    v2_groups.setdefault(fid, []).append(data)
                else:
                    raw_phases = data.pop("phases", [])
                    known_data = {k: v for k, v in data.items() if k in _build_fields}
                    rec = BuildMetrics(**known_data)
                    rec.phases = [
                        PhaseSnapshot(**{k: v for k, v in p.items() if k in _phase_fields})
                        for p in raw_phases
                    ]
                    v1_records.append(rec)
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                log.warning(
                    "metrics.jsonl line %d skipped (%s): %s",
                    line_no, type(exc).__name__, exc,
                )
                continue

    # Convert v2 groups into BuildMetrics for display compat.
    for fid, phase_dicts in v2_groups.items():
        bm = _v2_group_to_build_metrics(fid, phase_dicts)
        v1_records.append(bm)

    # Sort by timestamp, most recent first, take last `limit`.
    v1_records.sort(key=lambda r: r.timestamp, reverse=True)
    return v1_records[:limit]


def _v2_group_to_build_metrics(
    feature_id: str, phase_dicts: list[dict[str, Any]],
) -> BuildMetrics:
    """Reconstruct a BuildMetrics from a group of v2 per-phase records."""
    if not phase_dicts:
        return BuildMetrics(
            feature_id=feature_id, description="", workflow="",
            timestamp="", version=2,
        )

    first = phase_dicts[0]
    description = str(first.get("description", ""))
    workflow = str(first.get("workflow", ""))
    timestamp = str(first.get("ts_start", ""))

    total_cost = 0.0
    total_duration = 0.0
    total_in = 0
    total_out = 0
    total_cache_creation = 0
    total_cache_read = 0
    snapshots: list[PhaseSnapshot] = []
    all_success = True

    for pd in phase_dicts:
        tokens = pd.get("tokens", {})
        if not isinstance(tokens, dict):
            tokens = {}
        cost = float(pd.get("cost_usd", 0))
        dur = float(pd.get("duration_s", 0))
        t_in = int(tokens.get("in", 0))
        t_out = int(tokens.get("out", 0))
        c_read = int(tokens.get("cache_read", 0))
        c_create = int(tokens.get("cache_creation", 0))
        outcome = pd.get("outcome", "success")
        success = outcome == "success"

        total_cost += cost
        total_duration += dur
        total_in += t_in
        total_out += t_out
        total_cache_creation += c_create
        total_cache_read += c_read
        if not success:
            all_success = False

        snapshots.append(PhaseSnapshot(
            name=str(pd.get("phase", "")),
            model=str(pd.get("model", "")),
            cost_usd=cost,
            input_tokens=t_in,
            output_tokens=t_out,
            cache_creation=c_create,
            cache_read=c_read,
            duration_s=dur,
            success=success,
        ))

    failed_phase = None
    if not all_success:
        for s in reversed(snapshots):
            if not s.success:
                failed_phase = s.name
                break

    gate_phases = [s for s in snapshots if s.name == "gate"]
    gate_first = bool(gate_phases and gate_phases[0].success) if gate_phases else False

    return BuildMetrics(
        feature_id=feature_id,
        description=description,
        workflow=workflow,
        timestamp=timestamp,
        version=2,
        success=all_success,
        failed_phase=failed_phase,
        duration_s=round(total_duration, 1),
        cost_usd=round(total_cost, 4),
        input_tokens=total_in,
        output_tokens=total_out,
        cache_creation=total_cache_creation,
        cache_read=total_cache_read,
        gate_passed_first_try=gate_first,
        phases_total=len(snapshots),
        phases_completed=sum(1 for s in snapshots if s.success),
        phases=snapshots,
    )
