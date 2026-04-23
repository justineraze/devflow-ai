"""Rich display components for devflow-ai."""

from __future__ import annotations

from datetime import datetime

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from devflow.core.console import console
from devflow.core.formatting import format_cost, format_tokens
from devflow.core.history import BuildMetrics
from devflow.core.models import Feature, FeatureStatus, PhaseStatus, WorkflowState

# Status colors for visual feedback.
STATUS_COLORS: dict[str, str] = {
    "pending": "dim",
    "planning": "cyan",
    "plan_review": "cyan",
    "in_progress": "yellow",
    "implementing": "yellow",
    "reviewing": "blue",
    "fixing": "magenta",
    "gate": "blue",
    "done": "green",
    "blocked": "red",
    "failed": "red bold",
    "skipped": "dim",
}


def status_style(status: str) -> str:
    """Return the Rich style string for a given status."""
    return STATUS_COLORS.get(status, "white")


def render_header(title: str = "devflow-ai", subtitle: str = "") -> None:
    """Render the app header panel."""
    content = Text(title, style="bold cyan")
    if subtitle:
        content.append(f"\n{subtitle}", style="dim")
    console.print(Panel(content, border_style="cyan", padding=(0, 2)))


def _epic_status_cell(state: WorkflowState, epic_id: str) -> Text:
    """Build a status cell showing epic progress (e.g. '3/5 done')."""
    from devflow.core.epics import epic_progress

    progress = epic_progress(state, epic_id)
    if progress.all_done:
        return Text("done", style="green bold")
    parts = f"{progress.done}/{progress.total} done"
    if progress.in_progress:
        parts += f", {progress.in_progress} active"
    if progress.failed:
        parts += f", {progress.failed} blocked"
    return Text(parts, style="cyan")


def _add_feature_row(
    table: Table,
    feature: Feature,
    state: WorkflowState,
    indent: str = "",
) -> None:
    """Add a single feature row to the table, with optional indent."""
    is_epic = state.is_epic(feature.id)
    phase_info = _current_phase_info(feature)
    workflow_cell = feature.workflow
    if feature.metadata.complexity is not None:
        workflow_cell = f"{feature.workflow} ({feature.metadata.complexity.total}/12)"

    if is_epic:
        status_cell = _epic_status_cell(state, feature.id)
        phase_info = ""
    else:
        style = status_style(feature.status.value)
        status_cell = Text(feature.status.value, style=style)

    label = f"{indent}{feature.id}"
    table.add_row(
        label,
        _truncate(feature.description, 50),
        status_cell,
        workflow_cell,
        phase_info,
        feature.updated_at.strftime("%Y-%m-%d %H:%M"),
    )


def render_status_table(
    state: WorkflowState, include_archived: bool = False,
) -> None:
    """Render a table showing features and their current status.

    Epics are shown with their sub-features indented below them.
    Archived features (post-sync) are hidden by default.
    Pass ``include_archived=True`` to show them.
    """
    visible = [
        f for f in state.features.values()
        if include_archived or not f.metadata.archived
    ]
    if not visible:
        msg = "[dim]No features tracked yet.[/dim]"
        if not include_archived and state.features:
            msg = "[dim]No active features. Use --archived to show archived ones.[/dim]"
        console.print(msg)
        return

    table = Table(title="Features", border_style="dim")
    table.add_column("ID", style="bold")
    table.add_column("Description", max_width=50)
    table.add_column("Status")
    table.add_column("Workflow", style="dim")
    table.add_column("Phase")
    table.add_column("Updated")

    # Separate epics, children, and standalone features.
    child_ids = {f.id for f in visible if f.parent_id}
    rendered: set[str] = set()

    for feature in visible:
        if feature.id in rendered:
            continue

        if state.is_epic(feature.id):
            # Render epic header + children indented.
            _add_feature_row(table, feature, state)
            rendered.add(feature.id)
            for child in state.children_of(feature.id):
                if not include_archived and child.metadata.archived:
                    continue
                _add_feature_row(table, child, state, indent="  └ ")
                rendered.add(child.id)
        elif feature.id not in child_ids:
            # Standalone feature (no parent).
            _add_feature_row(table, feature, state)
            rendered.add(feature.id)

    console.print(table)


def render_feature_detail(feature: Feature) -> None:
    """Render detailed information about a single feature."""
    style = status_style(feature.status.value)
    console.print(f"\n[bold]{feature.id}[/bold] — {feature.description}")
    console.print(f"Status: [{style}]{feature.status.value}[/{style}]")
    console.print(f"Workflow: [dim]{feature.workflow}[/dim]")

    if feature.metadata.complexity is not None:
        c = feature.metadata.complexity
        console.print(
            f"Complexity: [dim]{c.total}/12 "
            f"(files:{c.files_touched} integrations:{c.integrations} "
            f"security:{c.security} scope:{c.scope})[/dim] "
            f"→ [bold]{c.workflow}[/bold]"
        )

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


def _format_duration(start: datetime, end: datetime) -> str:
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
        console.print("[dim]No features in history.[/dim]")
        return

    sorted_features = sorted(features, key=lambda f: f.created_at, reverse=True)

    table = Table(title="Feature log", border_style="dim")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Workflow", style="dim")
    table.add_column("Phases")
    table.add_column("Duration")
    table.add_column("Date", style="dim")

    for feature in sorted_features:
        style = status_style(feature.status.value)
        total = len(feature.phases)
        done = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
        duration = _format_duration(feature.created_at, feature.updated_at)
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
        console.print("[dim]No build history yet. Run a build to start tracking.[/dim]")
        return

    _render_last_build(records[0])

    if len(records) > 1:
        _render_phase_averages(records)

    _render_build_history(records)


def _render_last_build(record: BuildMetrics) -> None:
    """Render a summary panel for the most recent build."""
    success_style = "green" if record.success else "red bold"
    success_icon = "✓" if record.success else "✗"
    header = (
        f"[bold]{record.feature_id}[/bold]  "
        f"[{success_style}]{success_icon}[/{success_style}]  "
        f"[yellow]{format_cost(record.cost_usd)}[/yellow]  ·  "
        f"{_format_build_duration(record.duration_s)}  ·  "
        f"[dim]{record.timestamp[:10]}[/dim]"
    )
    console.print(Panel(header, title="Last build", border_style="dim", padding=(0, 1)))

    if not record.phases:
        return

    phase_table = Table(border_style="dim", padding=(0, 1))
    phase_table.add_column("Phase")
    phase_table.add_column("Model", style="dim")
    phase_table.add_column("Cost", justify="right")
    phase_table.add_column("Tokens", justify="right")
    phase_table.add_column("Cache%", justify="right")
    phase_table.add_column("Duration", justify="right")
    phase_table.add_column("", justify="center")

    for p in record.phases:
        total_tokens = p.input_tokens + p.cache_creation + p.cache_read
        cache_pct = f"{int(p.cache_read / total_tokens * 100)}%" if total_tokens > 0 else "—"
        p_icon = Text("✓", style="green") if p.success else Text("✗", style="red")
        row_style = "" if p.success else "red"
        phase_table.add_row(
            Text(p.name, style=row_style or "default"),
            p.model or "—",
            format_cost(p.cost_usd),
            format_tokens(p.input_tokens + p.cache_creation + p.cache_read),
            cache_pct,
            _format_build_duration(p.duration_s),
            p_icon,
            style=row_style,
        )

    console.print(phase_table)


def _render_phase_averages(records: list[BuildMetrics]) -> None:
    """Render avg cost/duration/tokens per phase type across all builds, sorted by cost."""
    acc: dict[str, dict[str, float | int]] = {}
    for r in records:
        for p in r.phases:
            if p.name not in acc:
                acc[p.name] = {"cost": 0.0, "duration": 0.0, "tokens": 0, "runs": 0}
            acc[p.name]["cost"] = float(acc[p.name]["cost"]) + p.cost_usd
            acc[p.name]["duration"] = float(acc[p.name]["duration"]) + p.duration_s
            total_tokens = p.input_tokens + p.cache_creation + p.cache_read
            acc[p.name]["tokens"] = int(acc[p.name]["tokens"]) + total_tokens
            acc[p.name]["runs"] = int(acc[p.name]["runs"]) + 1

    if not acc:
        return

    sorted_phases = sorted(
        acc.items(),
        key=lambda x: float(x[1]["cost"]) / int(x[1]["runs"]) if int(x[1]["runs"]) > 0 else 0.0,
        reverse=True,
    )

    table = Table(title="Avg cost by phase", border_style="dim")
    table.add_column("Phase", style="bold")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Avg Duration", justify="right")
    table.add_column("Avg Tokens", justify="right")
    table.add_column("Runs", justify="right", style="dim")

    total_avg_cost = 0.0
    total_avg_duration = 0.0
    total_avg_tokens = 0

    for name, data in sorted_phases:
        runs = int(data["runs"])
        avg_cost = float(data["cost"]) / runs
        avg_duration = float(data["duration"]) / runs
        avg_tokens = int(data["tokens"]) // runs
        total_avg_cost += avg_cost
        total_avg_duration += avg_duration
        total_avg_tokens += avg_tokens
        table.add_row(
            name,
            format_cost(avg_cost),
            _format_build_duration(avg_duration),
            format_tokens(avg_tokens),
            str(runs),
        )

    table.add_section()
    table.add_row(
        "[dim]Total avg[/dim]",
        Text(format_cost(total_avg_cost), style="yellow"),
        _format_build_duration(total_avg_duration),
        format_tokens(total_avg_tokens),
        "[dim]—[/dim]",
    )

    console.print(table)


def _render_build_history(records: list[BuildMetrics]) -> None:
    """Render the per-build history table with a summary line."""
    table = Table(title="Build history", border_style="dim")
    table.add_column("Feature", style="bold", max_width=28)
    table.add_column("", justify="center")  # status icon
    table.add_column("Cost", justify="right")
    table.add_column("Tokens in", justify="right")
    table.add_column("Cache %", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Gate", justify="center")
    table.add_column("Models", style="dim", max_width=20)
    table.add_column("Date", style="dim")

    for r in records:
        status_icon = Text("✓", style="green") if r.success else Text("✗", style="red")
        cache_pct = f"{int(r.cache_hit_rate * 100)}%"
        cache_style = "green" if r.cache_hit_rate > 0.5 else "yellow"
        duration = _format_build_duration(r.duration_s)

        if r.success:
            gate = "✓" if r.gate_passed_first_try else f"retry ×{r.gate_retries}"
            gate_style = "green" if r.gate_passed_first_try else "yellow"
        else:
            gate = r.failed_phase or "—"
            gate_style = "red"

        models = sorted({p.model for p in r.phases if p.model})
        models_str = ", ".join(models) if models else "—"

        table.add_row(
            _truncate(r.feature_id, 28),
            status_icon,
            Text(format_cost(r.cost_usd), style="yellow"),
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
            f"  [dim]{len(records)} builds · "
            f"{int(success_rate)}% success · "
            f"avg {format_cost(avg_cost)}/build · "
            f"avg cache {int(avg_cache * 100)}% · "
            f"total {format_cost(total_cost)}[/dim]"
        )


def _format_build_duration(seconds: float) -> str:
    """Format build duration for the metrics table."""
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def render_log_detail(feature: Feature) -> None:
    """Render detailed log view for a single feature."""
    style = status_style(feature.status.value)
    duration = _format_duration(feature.created_at, feature.updated_at)

    console.print(f"\n[bold]{feature.id}[/bold] — {feature.description}")
    console.print(f"Status: [{style}]{feature.status.value}[/{style}]")
    console.print(f"Workflow: [dim]{feature.workflow}[/dim]")
    if feature.metadata.complexity is not None:
        c = feature.metadata.complexity
        console.print(
            f"Complexity: [dim]{c.total}/12 "
            f"(files:{c.files_touched} integrations:{c.integrations} "
            f"security:{c.security} scope:{c.scope})[/dim] "
            f"→ [bold]{c.workflow}[/bold]"
        )
    console.print(f"Created: [dim]{feature.created_at.strftime('%Y-%m-%d %H:%M')}[/dim]")
    console.print(f"Duration: [dim]{duration}[/dim]")

    if not feature.phases:
        console.print("\n[dim]No phases recorded.[/dim]")
        return

    table = Table(title="Phases", border_style="dim")
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Error", max_width=60)

    for phase in feature.phases:
        ps = status_style(phase.status.value)
        marker = _phase_marker(phase.status)
        if phase.started_at and phase.completed_at:
            phase_duration = _format_duration(phase.started_at, phase.completed_at)
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
