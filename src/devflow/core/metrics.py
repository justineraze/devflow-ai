"""Shared DTOs for phase execution metrics.

Lives in core/ so both orchestration (which produces them) and ui
(which renders them) can depend on it without crossing layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolUse:
    """A tool invocation by the backend during a phase."""

    name: str
    summary: str


@dataclass
class PhaseMetrics:
    """Metrics extracted from the backend's stream-json result event."""

    duration_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    tool_count: int = 0
    tools_used: list[ToolUse] = field(default_factory=list)
    final_text: str = ""


@dataclass
class CommitInfo:
    """A single commit made during a phase execution."""

    sha: str
    message: str
    files: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0


@dataclass
class PhaseResult:
    """Observable output of a phase execution.

    Built AFTER a phase completes by comparing git state before/after.
    """

    success: bool
    output: str
    metrics: PhaseMetrics
    commits: list[CommitInfo] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    uncommitted_changes: bool = False


# ── Phase snapshot & build totals ─────────────────────────────────


@dataclass
class PhaseSnapshot:
    """Metrics snapshot for a single phase execution.

    Used both for in-memory tracking during a build (via BuildTotals)
    and for persistent history (serialized to metrics.jsonl).
    """

    name: str
    model: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    tool_count: int = 0
    duration_s: float = 0.0
    success: bool = True
    commits: int = 0
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass
class BuildTotals:
    """Running totals across all phases of a build."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    tool_count: int = 0
    duration_s: float = 0.0
    phase_durations: dict[str, float] = field(default_factory=dict)
    phase_snapshots: list[PhaseSnapshot] = field(default_factory=list)

    def add(
        self, phase_name: str, metrics: PhaseMetrics, elapsed_s: float,
        model: str = "", success: bool = True,
        commits: int = 0, files_changed: int = 0,
        insertions: int = 0, deletions: int = 0,
    ) -> None:
        self.cost_usd += metrics.cost_usd
        self.input_tokens += metrics.input_tokens
        self.output_tokens += metrics.output_tokens
        self.cache_creation += metrics.cache_creation
        self.cache_read += metrics.cache_read
        self.tool_count += metrics.tool_count
        self.duration_s += elapsed_s
        self.phase_durations[phase_name] = elapsed_s
        self.phase_snapshots.append(PhaseSnapshot(
            name=phase_name,
            model=model,
            cost_usd=metrics.cost_usd,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            cache_creation=metrics.cache_creation,
            cache_read=metrics.cache_read,
            tool_count=metrics.tool_count,
            duration_s=elapsed_s,
            success=success,
            commits=commits,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
        ))


def compute_cache_hit_rate(
    input_tokens: int, cache_creation: int, cache_read: int,
) -> float:
    """Fraction of input tokens served from cache (0.0–1.0)."""
    total = input_tokens + cache_creation + cache_read
    return cache_read / total if total > 0 else 0.0
