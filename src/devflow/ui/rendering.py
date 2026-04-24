"""Rich renderers for the build flow — banner, phase headers, summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from devflow.core.console import console
from devflow.core.formatting import format_cost, format_tokens
from devflow.core.metrics import (
    BuildTotals,
    PhaseMetrics,
    PhaseResult,
    PhaseSnapshot,
    compute_cache_hit_rate,
)
from devflow.core.models import Feature

if TYPE_CHECKING:
    from devflow.orchestration.sync import SyncResult

# Re-export for backwards compatibility (tests, external consumers).
PhaseMetricSnapshot = PhaseSnapshot

STACK_ICONS: dict[str, str] = {
    "python": "🐍",
    "typescript": "🟦",
    "php": "🐘",
    "javascript": "🟨",
}

MODEL_STYLES: dict[str, str] = {
    "opus": "magenta bold",
    "sonnet": "cyan bold",
    "haiku": "green bold",
}

PHASE_DOT_COLORS: dict[str, str] = {
    "done": "green",
    "failed": "red",
    "in_progress": "yellow",
    "pending": "dim",
    "skipped": "dim",
}


def _model_badge(model: str) -> Text:
    """Colored pill-style label for a Claude model tier."""
    style = MODEL_STYLES.get(model, "white bold")
    return Text(f" {model} ", style=f"reverse {style}", end="")


def _bar(ratio: float, width: int = 24) -> Text:
    """Unicode progress bar. Color shifts from green → yellow → red."""
    ratio = max(0.0, min(1.0, ratio))
    filled = int(width * ratio)
    if ratio < 0.6:
        color = "green"
    elif ratio < 0.85:
        color = "yellow"
    else:
        color = "red"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style="dim")
    return bar


def render_build_banner(feature: Feature, branch: str, stack: str | None) -> None:
    """Render the banner shown at the start of a build."""
    stack_label = (stack or "generic").lower()
    icon = STACK_ICONS.get(stack_label, "📦")
    total_phases = len(feature.phases)

    title = Text(feature.description, style="bold white")
    meta = Text()
    meta.append(feature.id, style="dim")
    meta.append("  ·  ", style="dim")
    meta.append(f"{icon} {stack_label}", style="cyan")
    meta.append("  ·  ", style="dim")
    meta.append(feature.workflow, style="cyan")
    meta.append("  ·  ", style="dim")
    meta.append(f"{total_phases} phases", style="cyan")

    if feature.metadata.linear_issue_key:
        meta.append("  ·  ", style="dim")
        meta.append(f"Linear: {feature.metadata.linear_issue_key}", style="cyan")

    branch_line = Text()
    branch_line.append("🌿 ", style="green")
    branch_line.append(branch, style="dim")

    content = Group(title, meta, branch_line)
    console.print()
    console.print(Rule(style="cyan"))
    console.print(content)
    console.print(Rule(style="cyan"))
    console.print()


def render_phase_header(
    phase_num: int, total: int, phase_name: str, model: str,
) -> None:
    """Header line printed when a phase starts."""
    header = Text()
    header.append("▶ ", style="cyan bold")
    header.append(f"phase {phase_num}/{total} · ", style="dim")
    header.append(phase_name, style="bold")
    header.append("   ")
    header.append_text(_model_badge(model))
    console.print(header)


def render_phase_success(
    phase_name: str, elapsed_s: float, metrics: PhaseMetrics,
) -> None:
    """One-line summary chip printed when a phase completes successfully."""
    chip = Text("  ")
    chip.append("✓ ", style="green bold")
    chip.append(phase_name, style="bold")
    chip.append(f"   {_fmt_duration(elapsed_s)}", style="dim")

    if metrics.tool_count:
        chip.append(f"   {metrics.tool_count} tools", style="dim")

    if metrics.cost_usd:
        chip.append(f"   {format_cost(metrics.cost_usd)}", style="yellow")

    cache_rate = compute_cache_hit_rate(
        metrics.input_tokens, metrics.cache_creation, metrics.cache_read,
    )
    if cache_rate > 0:
        pct = int(cache_rate * 100)
        chip.append(f"   cache {pct}%", style="green" if pct >= 80 else "yellow")

    console.print(chip)
    console.print()


def render_phase_failure(phase_name: str, elapsed_s: float, message: str) -> None:
    """One-line failure chip for a phase."""
    chip = Text("  ")
    chip.append("✗ ", style="red bold")
    chip.append(phase_name, style="bold")
    chip.append(f"   {_fmt_duration(elapsed_s)}", style="dim")
    console.print(chip)
    for line in message.split("\n")[:5]:
        if line.strip():
            console.print(Text(f"    {line}", style="dim"))
    console.print()


def render_phase_auto_retry(phase_name: str, elapsed_s: float, message: str) -> None:
    """Distinct chip used when a failing gate is about to be auto-retried."""
    chip = Text("  ")
    chip.append("↻ ", style="yellow bold")
    chip.append(f"{phase_name} failed — auto-retrying via fixing", style="yellow")
    chip.append(f"   {_fmt_duration(elapsed_s)}", style="dim")
    console.print(chip)
    for line in message.split("\n")[:8]:
        if line.strip():
            console.print(Text(f"    {line}", style="dim"))
    console.print()


def render_phase_commits(phase_result: PhaseResult) -> None:
    """Render a detailed commit summary after an implementing/fixing phase.

    Shows all commits made by the agent during the phase, plus any
    auto-committed leftovers. Replaces the old single-diff display.
    """
    commits = phase_result.commits
    if not commits and not phase_result.uncommitted_changes:
        return

    total_ins = sum(c.insertions for c in commits)
    total_del = sum(c.deletions for c in commits)
    total_files = len(phase_result.files_changed)

    if len(commits) == 1:
        c = commits[0]
        line = Text("  ")
        line.append(f"  {c.sha} ", style="cyan dim")
        line.append(c.message, style="dim")
        console.print(line)
        stat = Text("  ")
        stat.append(
            f"  {len(c.files)} file{'s' if len(c.files) != 1 else ''} changed",
            style="dim",
        )
        if c.insertions:
            ins_s = "s" if c.insertions != 1 else ""
            stat.append(f", {c.insertions} insertion{ins_s}(+)", style="green dim")
        if c.deletions:
            del_s = "s" if c.deletions != 1 else ""
            stat.append(f", {c.deletions} deletion{del_s}(-)", style="red dim")
        console.print(stat)
    elif len(commits) > 1:
        for c in commits:
            line = Text("  ")
            line.append(f"  {c.sha} ", style="cyan dim")
            line.append(c.message, style="dim")
            detail = f" ({len(c.files)} file{'s' if len(c.files) != 1 else ''}, +{c.insertions}"
            if c.deletions:
                detail += f", -{c.deletions}"
            detail += ")"
            line.append(detail, style="dim")
            console.print(line)

        # Total line.
        total = Text("  ")
        total.append(
            f"  Total: {total_files} file{'s' if total_files != 1 else ''} changed",
            style="dim bold",
        )
        if total_ins:
            ins_s = "s" if total_ins != 1 else ""
            total.append(f", {total_ins} insertion{ins_s}(+)", style="green dim")
        if total_del:
            del_s = "s" if total_del != 1 else ""
            total.append(f", {total_del} deletion{del_s}(-)", style="red dim")
        console.print(total)

    console.print()


def render_build_summary(
    feature: Feature,
    totals: BuildTotals,
    pr_url: str | None,
    branch: str,
    cost_budget: float | None = None,
) -> None:
    """Final multi-block panel shown when a build completes."""
    phase_dots = _render_phase_timeline(feature, totals)

    grid = Table.grid(expand=False, padding=(0, 2))
    grid.add_column(justify="right", style="dim")
    grid.add_column()

    grid.add_row("Duration", _fmt_duration(totals.duration_s))
    grid.add_row("Cost", Text(format_cost(totals.cost_usd), style="yellow bold"))
    grid.add_row("Tools", str(totals.tool_count))

    cache_rate = compute_cache_hit_rate(
        totals.input_tokens, totals.cache_creation, totals.cache_read,
    )
    if cache_rate > 0:
        cache_pct = int(cache_rate * 100)
        cache_style = "green" if cache_pct >= 80 else "yellow"
        total_in = totals.input_tokens + totals.cache_creation + totals.cache_read
        cache_text = Text()
        cache_text.append(f"{cache_pct}%", style=cache_style)
        cache_text.append(
            f" ({format_tokens(totals.cache_read)} read / {format_tokens(total_in)} total)",
            style="dim",
        )
        grid.add_row("Cache", cache_text)

    # Cost breakdown by model tier.
    model_costs: dict[str, float] = {}
    for snap in totals.phase_snapshots:
        tier = snap.model or "unknown"
        model_costs[tier] = model_costs.get(tier, 0.0) + snap.cost_usd
    if model_costs:
        cost_parts = Text()
        for i, (tier, cost) in enumerate(sorted(model_costs.items(), key=lambda x: -x[1])):
            if i > 0:
                cost_parts.append(", ", style="dim")
            style = MODEL_STYLES.get(tier, "white bold")
            cost_parts.append(tier, style=style)
            cost_parts.append(f" {format_cost(cost)}", style="dim")
        grid.add_row("Cost by model", cost_parts)

    rows: list[Text | Table] = [grid, Text()]

    if cost_budget and cost_budget > 0:
        ratio = totals.cost_usd / cost_budget
        rows.append(_budget_row("Cost    ", _bar(ratio), format_cost(totals.cost_usd),
                                f"/ {format_cost(cost_budget)}", f"{int(ratio * 100)}%"))

    rows.append(Text())
    rows.append(phase_dots)

    if pr_url:
        rows.append(Text())
        link = Text()
        link.append("🔗 ", style="green")
        link.append(pr_url, style="blue underline")
        if feature.metadata.linear_issue_key:
            link.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style="cyan")
        rows.append(link)
    else:
        rows.append(Text())
        hint = Text()
        hint.append("branch: ", style="dim")
        hint.append(branch, style="dim")
        if feature.metadata.linear_issue_key:
            hint.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style="cyan")
        rows.append(hint)

    console.print()
    console.print(Panel(
        Group(*rows),
        title=Text(" ✓ Build complete ", style="reverse green bold"),
        border_style="green",
        padding=(1, 2),
    ))


def _budget_row(
    label: str, bar: Text, value: str, of_value: str, pct: str,
) -> Text:
    row = Text()
    row.append(label, style="dim")
    row.append_text(bar)
    row.append(f"  {value} {of_value}  ", style="dim")
    row.append(pct.rjust(4), style="bold")
    return row


def _render_phase_timeline(feature: Feature, totals: BuildTotals) -> Table:
    """Compact two-line dot/duration grid for the build summary panel."""
    grid = Table.grid(padding=(0, 2), expand=False)
    for _ in feature.phases:
        grid.add_column(no_wrap=True)

    dots: list[Text] = []
    labels: list[Text] = []
    for phase in feature.phases:
        color = PHASE_DOT_COLORS.get(phase.status.value, "dim")
        dot = Text(f"● {phase.name}", style=color)
        elapsed = totals.phase_durations.get(phase.name)
        label = Text(
            _fmt_duration(elapsed) if elapsed else "—",
            style="dim",
        )
        dots.append(dot)
        labels.append(label)

    grid.add_row(*dots)
    grid.add_row(*labels)
    return grid


def render_sync_summary(result: SyncResult) -> None:
    """Render a Rich panel summarising the outcome of ``devflow sync``."""
    prefix = "[yellow]dry-run[/yellow] " if result.dry_run else ""

    grid = Table.grid(expand=False, padding=(0, 2))
    grid.add_column(justify="right", style="dim")
    grid.add_column()

    # Branches row.
    branch_text = Text()
    if result.branches_deleted:
        branch_text.append(str(len(result.branches_deleted)), style="bold red")
        branch_text.append(" deleted", style="dim")
        branch_text.append(f"  ({', '.join(result.branches_deleted)})", style="dim")
    else:
        branch_text.append("none", style="dim")
    grid.add_row("Branches", branch_text)

    # Features row.
    feat_text = Text()
    if result.features_archived:
        feat_text.append(str(len(result.features_archived)), style="bold green")
        feat_text.append(" archived", style="dim")
        feat_text.append(f"  ({', '.join(result.features_archived)})", style="dim")
    else:
        feat_text.append("none", style="dim")
    grid.add_row("Features archived", feat_text)

    # Current branch.
    cb_text = Text(result.current_branch or "—", style="cyan")
    grid.add_row("Current branch", cb_text)

    rows: list[Text | Table] = [grid]

    if result.dry_run and result.actions:
        rows.append(Text())
        rows.append(Text("Actions that would run:", style="yellow dim"))
        for action in result.actions:
            rows.append(Text(f"  • {action}", style="dim"))

    title_style = "reverse yellow bold" if result.dry_run else "reverse green bold"
    title_label = "⏵ Sync (dry-run)" if result.dry_run else "✓ Sync complete"

    console.print()
    console.print(Panel(
        Group(*rows),
        title=Text(f" {prefix}{title_label} ", style=title_style),
        border_style="yellow" if result.dry_run else "green",
        padding=(1, 2),
    ))


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{int(round(seconds))}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"
