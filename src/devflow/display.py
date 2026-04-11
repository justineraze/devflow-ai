"""Rich display components for devflow-ai."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from devflow.models import Feature, FeatureStatus, PhaseStatus, WorkflowState

console = Console()

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


def render_status_table(state: WorkflowState) -> None:
    """Render a table showing all features and their current status."""
    if not state.features:
        console.print("[dim]No features tracked yet.[/dim]")
        return

    table = Table(title="Features", border_style="dim")
    table.add_column("ID", style="bold")
    table.add_column("Description", max_width=50)
    table.add_column("Status")
    table.add_column("Workflow", style="dim")
    table.add_column("Phase")
    table.add_column("Updated")

    for feature in state.features.values():
        style = status_style(feature.status.value)
        phase_info = _current_phase_info(feature)
        table.add_row(
            feature.id,
            _truncate(feature.description, 50),
            Text(feature.status.value, style=style),
            feature.workflow,
            phase_info,
            feature.updated_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


def render_feature_detail(feature: Feature) -> None:
    """Render detailed information about a single feature."""
    style = status_style(feature.status.value)
    console.print(f"\n[bold]{feature.id}[/bold] — {feature.description}")
    console.print(f"Status: [{style}]{feature.status.value}[/{style}]")
    console.print(f"Workflow: [dim]{feature.workflow}[/dim]")

    if feature.phases:
        console.print("\nPhases:")
        for _i, phase in enumerate(feature.phases, 1):
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
