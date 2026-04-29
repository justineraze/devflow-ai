"""Rich display components for devflow-ai."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from devflow.core.console import console, is_quiet
from devflow.core.epics import epic_progress
from devflow.core.formatting import format_cost, format_duration, format_tokens
from devflow.core.history import BuildMetrics
from devflow.core.kpis import MetricsDashboard
from devflow.core.models import Feature, FeatureStatus, PhaseStatus, WorkflowState
from devflow.ui import theme
from devflow.ui.theme import m as _m


@dataclass
class _PhaseAccumulator:
    """Running totals for a single phase type across multiple builds."""

    cost: float = 0.0
    duration: float = 0.0
    tokens: int = 0
    runs: int = 0
    cache_read: int = 0
    cache_total: int = 0


def status_style(status: str) -> str:
    """Return the Rich style string for a given status."""
    return theme.STATUS_STYLES.get(status, theme.TEXT)


def render_header(title: str = "devflow-ai", subtitle: str = "") -> None:
    """Render the app header panel."""
    if is_quiet():
        return
    content = Text(title, style=f"bold {theme.ACCENT}")
    if subtitle:
        content.append(f"\n{subtitle}", style=theme.TEXT_MUTED)
    console.print(Panel(content, border_style=theme.ACCENT, padding=(0, 2)))


def _epic_status_cell(state: WorkflowState, epic_id: str) -> Text:
    """Build a status cell showing epic progress (e.g. '3/5 done')."""
    progress = epic_progress(state, epic_id)
    if progress.all_done:
        return Text("done", style=f"{theme.SUCCESS} bold")
    parts = f"{progress.done}/{progress.total} done"
    if progress.in_progress:
        parts += f", {progress.in_progress} active"
    if progress.failed:
        parts += f", {progress.failed} blocked"
    return Text(parts, style=theme.ACCENT)


def _relative_time(dt: datetime) -> str:
    """Format a datetime as a relative time string (e.g. '2h ago')."""
    now = datetime.now(tz=dt.tzinfo or UTC)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return f"{days}d ago" if days < 7 else dt.strftime("%Y-%m-%d")


def _add_status_row(
    grid: Table,
    feature: Feature,
    state: WorkflowState,
    indent: str = "",
) -> None:
    """Add one compact row to the status grid."""
    label = f"{indent}{feature.id}"

    if state.is_epic(feature.id):
        progress = epic_progress(state, feature.id)
        status_text = Text(f"{progress.done}/{progress.total} done", style=theme.ACCENT)
    else:
        style = status_style(feature.status.value)
        status_text = Text(feature.status.value, style=style)

    wf = feature.workflow
    duration = _format_elapsed(feature.created_at, feature.updated_at)
    age = _relative_time(feature.updated_at)
    wt = " [wt]" if feature.metadata.worktree_path else ""

    grid.add_row(
        Text(label, style="bold"),
        status_text,
        Text(wf, style=theme.TEXT_MUTED),
        Text(duration, style=theme.TEXT_DIM),
        Text(f"{age}{wt}", style=theme.TEXT_MUTED),
    )


def render_status_table(
    state: WorkflowState, include_archived: bool = False,
) -> None:
    """Render a compact grid of features with aligned columns."""
    visible = [
        f for f in state.features.values()
        if include_archived or not f.metadata.archived
    ]
    if not visible:
        msg = _m(theme.TEXT_MUTED, "No features tracked yet.")
        if not include_archived and state.features:
            msg = _m(
                theme.TEXT_MUTED,
                "No active features. Use --archived to show archived ones.",
            )
        console.print(msg)
        return

    grid = Table.grid(padding=(0, 2))
    grid.add_column()
    grid.add_column()
    grid.add_column()
    grid.add_column(justify="right")
    grid.add_column()

    child_ids = {f.id for f in visible if f.parent_id}
    rendered: set[str] = set()
    count = 0
    done_count = 0
    failed_count = 0

    for feature in visible:
        if feature.id in rendered:
            continue

        if state.is_epic(feature.id):
            _add_status_row(grid, feature, state)
            rendered.add(feature.id)
            count += 1
            for child in state.children_of(feature.id):
                if not include_archived and child.metadata.archived:
                    continue
                _add_status_row(grid, child, state, indent="  └ ")
                rendered.add(child.id)
                count += 1
                if child.status == FeatureStatus.DONE:
                    done_count += 1
                elif child.status == FeatureStatus.FAILED:
                    failed_count += 1
        elif feature.id not in child_ids:
            _add_status_row(grid, feature, state)
            rendered.add(feature.id)
            count += 1
            if feature.status == FeatureStatus.DONE:
                done_count += 1
            elif feature.status == FeatureStatus.FAILED:
                failed_count += 1

    console.print()
    console.print(grid)

    parts = [f"{count} feature{'s' if count != 1 else ''}"]
    if done_count:
        parts.append(f"{done_count} done")
    if failed_count:
        parts.append(f"{failed_count} failed")
    console.print()
    console.print(_m(theme.TEXT_MUTED, "  " + " · ".join(parts)))


def render_feature_detail(feature: Feature) -> None:
    """Render detailed information about a single feature."""
    style = status_style(feature.status.value)
    console.print(f"\n[bold]{feature.id}[/bold] — {feature.description}")
    console.print(f"Status: [{style}]{feature.status.value}[/{style}]")
    console.print(f"Workflow: {_m(theme.TEXT_MUTED, feature.workflow)}")

    if feature.metadata.worktree_path:
        console.print(f"Worktree: {_m(theme.TEXT_MUTED, str(feature.metadata.worktree_path))}")

    if feature.metadata.complexity is not None:
        c = feature.metadata.complexity
        detail = (
            f"{c.total}/12 (files:{c.files_touched} integrations:{c.integrations} "
            f"security:{c.security} scope:{c.scope})"
        )
        console.print(f"Complexity: {_m(theme.TEXT_MUTED, detail)} → [bold]{c.workflow}[/bold]")

    if feature.phases:
        console.print("\nPhases:")
        for phase in feature.phases:
            ps = status_style(phase.status.value)
            marker = _phase_marker(phase.status)
            console.print(f"  {marker} [{ps}]{phase.name}[/{ps}]")


def render_phase_progress(feature: Feature) -> None:
    """Render a compact progress bar for feature phases."""
    total = len(feature.phases)
    done = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
    console.print(f"[bold]{feature.id}[/bold] [{done}/{total}] ", end="")
    for phase in feature.phases:
        marker = _phase_marker(phase.status)
        console.print(marker, end="")
    console.print()


def _current_phase_info(feature: Feature) -> str:
    """Return a string describing the current phase."""
    current = feature.current_phase
    if current:
        return current.name
    if feature.status == FeatureStatus.DONE:
        return "✓ all done"
    if feature.status == FeatureStatus.FAILED:
        return "✗ failed"
    # Find first pending phase.
    for phase in feature.phases:
        if phase.status == PhaseStatus.PENDING:
            return f"→ {phase.name}"
    return ""


def _phase_marker(status: PhaseStatus) -> str:
    """Return an emoji marker for a phase status."""
    return {
        PhaseStatus.PENDING: "○",
        PhaseStatus.IN_PROGRESS: "◉",
        PhaseStatus.DONE: "●",
        PhaseStatus.SKIPPED: "◌",
        PhaseStatus.FAILED: "✗",
    }.get(status, "?")


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _format_elapsed(start: datetime, end: datetime) -> str:
    """Format the duration between two datetimes as a human-readable string."""
    total_seconds = int((end - start).total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        if remaining_minutes:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"
    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def render_log_table(features: list[Feature]) -> None:
    """Render a summary table of features sorted by created_at descending."""
    if not features:
        console.print(_m(theme.TEXT_MUTED, "No features in history."))
        return

    sorted_features = sorted(features, key=lambda f: f.created_at, reverse=True)

    table = Table(title="Feature log", border_style=theme.TEXT_MUTED)
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Workflow", style=theme.TEXT_MUTED)
    table.add_column("Phases")
    table.add_column("Duration")
    table.add_column("Date", style=theme.TEXT_MUTED)

    for feature in sorted_features:
        style = status_style(feature.status.value)
        total = len(feature.phases)
        done = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
        duration = _format_elapsed(feature.created_at, feature.updated_at)
        table.add_row(
            feature.id,
            Text(feature.status.value, style=style),
            feature.workflow,
            f"{done}/{total}",
            duration,
            feature.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


def render_metrics_table(records: list[BuildMetrics]) -> None:
    """Render build metrics: last build summary, phase averages, build history."""
    if not records:
        console.print(_m(theme.TEXT_MUTED, "No build history yet. Run a build to start tracking."))
        return

    _render_last_build(records[0])

    if len(records) > 1:
        _render_phase_averages(records)

    _render_build_history(records)


def _render_last_build(record: BuildMetrics) -> None:
    """Render a summary panel for the most recent build."""
    success_style = theme.SUCCESS if record.success else f"{theme.ERROR} bold"
    success_icon = "✓" if record.success else "✗"
    header = (
        f"[bold]{record.feature_id}[/bold]  "
        f"[{success_style}]{success_icon}[/{success_style}]  "
        f"{_m(theme.COST, format_cost(record.cost_usd))}  ·  "
        f"{format_duration(record.duration_s)}  ·  "
        f"{_m(theme.TEXT_MUTED, record.timestamp[:10])}"
    )
    console.print(Panel(header, title="Last build", border_style=theme.TEXT_MUTED, padding=(0, 1)))

    if not record.phases:
        return

    phase_table = Table(border_style=theme.TEXT_MUTED, padding=(0, 1))
    phase_table.add_column("Phase")
    phase_table.add_column("Model", style=theme.TEXT_MUTED)
    phase_table.add_column("Cost", justify="right")
    phase_table.add_column("Tokens", justify="right")
    phase_table.add_column("Cache%", justify="right")
    phase_table.add_column("Changes", justify="right", style=theme.TEXT_MUTED)
    phase_table.add_column("Duration", justify="right")
    phase_table.add_column("", justify="center")

    for p in record.phases:
        total_tokens = p.input_tokens + p.cache_creation + p.cache_read
        cache_pct = f"{int(p.cache_read / total_tokens * 100)}%" if total_tokens > 0 else "—"
        p_icon = Text("✓", style=theme.SUCCESS) if p.success else Text("✗", style=theme.ERROR)
        row_style = "" if p.success else theme.ERROR

        # Show commit/change stats if available.
        changes = ""
        if p.commits:
            parts = [f"{p.commits} commit{'s' if p.commits != 1 else ''}"]
            if p.insertions or p.deletions:
                parts.append(f"+{p.insertions}/-{p.deletions}")
            changes = " ".join(parts)

        phase_table.add_row(
            Text(p.name, style=row_style or "default"),
            p.model or "—",
            format_cost(p.cost_usd),
            format_tokens(p.input_tokens + p.cache_creation + p.cache_read),
            cache_pct,
            changes,
            format_duration(p.duration_s),
            p_icon,
            style=row_style,
        )

    console.print(phase_table)


def _accumulate_phase_stats(
    records: list[BuildMetrics],
) -> dict[str, _PhaseAccumulator]:
    """Aggregate per-phase totals across multiple build records."""
    acc: dict[str, _PhaseAccumulator] = {}
    for r in records:
        for p in r.phases:
            a = acc.setdefault(p.name, _PhaseAccumulator())
            a.cost += p.cost_usd
            a.duration += p.duration_s
            total_tokens = p.input_tokens + p.cache_creation + p.cache_read
            a.tokens += total_tokens
            a.cache_read += p.cache_read
            a.cache_total += total_tokens
            a.runs += 1
    return acc


def _phase_average_row(name: str, a: _PhaseAccumulator) -> tuple[str, Text, str, str, Text, str]:
    """Build one row for the phase-averages table."""
    avg_cost = a.cost / a.runs
    avg_duration = a.duration / a.runs
    avg_tokens = a.tokens // a.runs

    if a.cache_total > 0:
        cpct = int(a.cache_read / a.cache_total * 100)
        cache_style = theme.CACHE_GOOD if cpct >= 60 else theme.CACHE_LOW
        cache_cell = Text(f"{cpct}%", style=cache_style)
    else:
        cache_cell = Text("—", style=theme.TEXT_MUTED)

    return (
        name,
        Text(format_cost(avg_cost)),
        format_duration(avg_duration),
        format_tokens(avg_tokens),
        cache_cell,
        str(a.runs),
    )


def _render_phase_averages(records: list[BuildMetrics]) -> None:
    """Render avg cost/duration/tokens per phase type across all builds, sorted by cost."""
    acc = _accumulate_phase_stats(records)
    if not acc:
        return

    sorted_phases = sorted(
        acc.items(),
        key=lambda x: x[1].cost / x[1].runs if x[1].runs > 0 else 0.0,
        reverse=True,
    )

    table = Table(title="Avg cost by phase", border_style=theme.TEXT_MUTED)
    table.add_column("Phase", style="bold")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Avg Duration", justify="right")
    table.add_column("Avg Tokens", justify="right")
    table.add_column("Cache %", justify="right")
    table.add_column("Runs", justify="right", style=theme.TEXT_MUTED)

    total_avg_cost = 0.0
    total_avg_duration = 0.0
    total_avg_tokens = 0
    total_cache_read = 0
    total_cache_total = 0

    for name, a in sorted_phases:
        total_avg_cost += a.cost / a.runs
        total_avg_duration += a.duration / a.runs
        total_avg_tokens += a.tokens // a.runs
        total_cache_read += a.cache_read
        total_cache_total += a.cache_total
        table.add_row(*_phase_average_row(name, a))

    if total_cache_total > 0:
        total_cpct = int(total_cache_read / total_cache_total * 100)
        total_cache_style = theme.CACHE_GOOD if total_cpct >= 60 else theme.CACHE_LOW
        total_cache_cell = Text(f"{total_cpct}%", style=total_cache_style)
    else:
        total_cache_cell = Text("—", style=theme.TEXT_MUTED)

    table.add_section()
    table.add_row(
        _m(theme.TEXT_MUTED, "Total avg"),
        Text(format_cost(total_avg_cost), style=theme.COST),
        format_duration(total_avg_duration),
        format_tokens(total_avg_tokens),
        total_cache_cell,
        _m(theme.TEXT_MUTED, "—"),
    )

    console.print(table)


def _aggregate_model_costs(record: BuildMetrics) -> dict[str, float]:
    """Sum cost per model tier across all phases of a single build record."""
    model_costs: dict[str, float] = {}
    for p in record.phases:
        tier = p.model or "unknown"
        model_costs[tier] = model_costs.get(tier, 0.0) + p.cost_usd
    return model_costs


def _render_build_history(records: list[BuildMetrics]) -> None:
    """Render the per-build history table with a summary line."""
    table = Table(title="Build history", border_style=theme.TEXT_MUTED)
    table.add_column("Feature", style="bold", max_width=28)
    table.add_column("", justify="center")  # status icon
    table.add_column("Cost", justify="right")
    table.add_column("Tokens in", justify="right")
    table.add_column("Cache %", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Gate", justify="center")
    table.add_column("Models", style=theme.TEXT_MUTED, max_width=20)
    table.add_column("Date", style=theme.TEXT_MUTED)

    for r in records:
        status_icon = Text("✓", style=theme.SUCCESS) if r.success else Text("✗", style=theme.ERROR)
        cache_pct = f"{int(r.cache_hit_rate * 100)}%"
        cache_style = theme.CACHE_GOOD if r.cache_hit_rate > 0.5 else theme.CACHE_LOW
        duration = format_duration(r.duration_s)

        if r.success:
            gate = "✓" if r.gate_passed_first_try else f"retry ×{r.gate_retries}"
            gate_style = theme.SUCCESS if r.gate_passed_first_try else theme.WARNING
        else:
            gate = r.failed_phase or "—"
            gate_style = theme.ERROR

        model_costs = _aggregate_model_costs(r)
        if model_costs:
            parts = []
            for tier, cost in sorted(model_costs.items(), key=lambda x: -x[1]):
                parts.append(f"{tier} {format_cost(cost)}")
            models_str = " · ".join(parts)
        else:
            models_str = "—"

        table.add_row(
            _truncate(r.feature_id, 28),
            status_icon,
            Text(format_cost(r.cost_usd), style=theme.COST),
            format_tokens(r.input_tokens + r.cache_creation + r.cache_read),
            Text(cache_pct, style=cache_style),
            duration,
            Text(gate, style=gate_style),
            models_str,
            r.timestamp[:10],
        )

    console.print(table)

    if len(records) > 1:
        successes = [r for r in records if r.success]
        avg_cost = sum(r.cost_usd for r in records) / len(records)
        avg_cache = sum(r.cache_hit_rate for r in records) / len(records)
        total_cost = sum(r.cost_usd for r in records)
        success_rate = len(successes) / len(records) * 100
        console.print(
            _m(theme.TEXT_MUTED,
               f"  {len(records)} builds · "
               f"{int(success_rate)}% success · "
               f"avg {format_cost(avg_cost)}/build · "
               f"avg cache {int(avg_cache * 100)}% · "
               f"total {format_cost(total_cost)}")
        )



def render_metrics_dashboard(dashboard: MetricsDashboard) -> None:
    """Render actionable metrics insights — no panels, just text."""
    if dashboard.total_features == 0:
        console.print(_m(theme.TEXT_MUTED, "No metrics data. Run a build to start tracking."))
        return

    n = dashboard.total_features
    gate_pct = int(dashboard.gate_first_try_rate * 100)
    median_str = _format_compact_duration(dashboard.time_to_pr_median_s)
    cache_pct = int(dashboard.cache_hit_rate * 100)
    cache_style = theme.CACHE_GOOD if cache_pct >= 60 else theme.CACHE_LOW

    headline = Text()
    headline.append(f"  {n} build{'s' if n != 1 else ''}", style="bold")
    headline.append(" · ", style=theme.SEPARATOR)
    headline.append(format_cost(dashboard.total_cost), style=theme.COST)
    headline.append(" · ", style=theme.SEPARATOR)
    headline.append(f"{gate_pct}% gate first-try", style="bold")
    headline.append(" · ", style=theme.SEPARATOR)
    headline.append(f"median {median_str} to PR", style=theme.TEXT_DIM)
    headline.append(" · ", style=theme.SEPARATOR)
    headline.append(f"cache {cache_pct}%", style=cache_style)
    console.print()
    console.print(headline)

    if dashboard.top_features_by_cost:
        console.print()
        top = dashboard.top_features_by_cost
        if top:
            fid, cost = top[0]
            pct = int(cost / dashboard.total_cost * 100) if dashboard.total_cost else 0
            line = Text("  most expensive   ", style=theme.TEXT_MUTED)
            line.append(f"{fid:<24}", style="bold")
            line.append(f" {format_cost(cost)}", style=theme.COST)
            line.append(f" ({pct}%)", style=theme.TEXT_MUTED)
            console.print(line)

    if dashboard.cost_by_backend:
        parts = []
        for b, c in sorted(dashboard.cost_by_backend.items(), key=lambda x: -x[1]):
            parts.append(f"{b} {format_cost(c)}")
        line = Text("  by backend       ", style=theme.TEXT_MUTED)
        line.append("  ".join(parts), style=theme.TEXT_DIM)
        console.print(line)

    if dashboard.budget_warnings:
        console.print()
        for fid, cost, limit in dashboard.budget_warnings:
            warn = f"⚠ {fid} exceeded budget ({format_cost(cost)} > {format_cost(limit)})"
            console.print(f"  {_m(theme.WARNING, warn)}")

    console.print()


def _format_compact_duration(seconds: float) -> str:
    """Format seconds as compact human string (e.g. '4m12s', '1h30m')."""
    if seconds <= 0:
        return "—"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    secs = total % 60
    if minutes < 60:
        return f"{minutes}m{secs:02d}s" if secs else f"{minutes}m"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f"{hours}h{remaining:02d}m"
    return f"{hours}h"


def render_log_detail(feature: Feature) -> None:
    """Render detailed log view for a single feature."""
    style = status_style(feature.status.value)
    duration = _format_elapsed(feature.created_at, feature.updated_at)

    console.print(f"\n[bold]{feature.id}[/bold] — {feature.description}")
    console.print(f"Status: [{style}]{feature.status.value}[/{style}]")
    console.print(f"Workflow: {_m(theme.TEXT_MUTED, feature.workflow)}")
    if feature.metadata.complexity is not None:
        c = feature.metadata.complexity
        detail = (
            f"{c.total}/12 (files:{c.files_touched} integrations:{c.integrations} "
            f"security:{c.security} scope:{c.scope})"
        )
        console.print(f"Complexity: {_m(theme.TEXT_MUTED, detail)} → [bold]{c.workflow}[/bold]")
    created = feature.created_at.strftime("%Y-%m-%d %H:%M")
    console.print(f"Created: {_m(theme.TEXT_MUTED, created)}")
    console.print(f"Duration: {_m(theme.TEXT_MUTED, duration)}")

    if not feature.phases:
        console.print(f"\n{_m(theme.TEXT_MUTED, 'No phases recorded.')}")
        return

    table = Table(title="Phases", border_style=theme.TEXT_MUTED)
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Error", max_width=60)

    for phase in feature.phases:
        ps = status_style(phase.status.value)
        marker = _phase_marker(phase.status)
        if phase.started_at and phase.completed_at:
            phase_duration = _format_elapsed(phase.started_at, phase.completed_at)
        else:
            phase_duration = "—"
        error = _truncate(phase.error, 60) if phase.error else ""
        table.add_row(
            phase.name,
            Text(f"{marker} {phase.status.value}", style=ps),
            phase_duration,
            error,
        )

    console.print(table)
