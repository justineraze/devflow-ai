"""Rich renderers for the build flow — banner, phase headers, summaries."""

from __future__ import annotations

import contextlib
import sys

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from devflow.core.console import console
from devflow.core.formatting import format_cost, format_duration, format_tokens
from devflow.core.gate_report import GateReport
from devflow.core.metrics import (
    BuildTotals,
    CommitInfo,
    PhaseMetrics,
    PhaseResult,
    PhaseSnapshot,
    compute_cache_hit_rate,
)
from devflow.core.models import Feature, SyncResult

# Backward-compat alias used by tests; prefer importing PhaseSnapshot from
# devflow.core.metrics in new code.
PhaseMetricSnapshot = PhaseSnapshot  # noqa: F401


def _plural(n: int, word: str) -> str:
    """Return ``word`` with an 's' appended when ``n`` is not 1."""
    return f"{word}{'s' if n != 1 else ''}"


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
    chip.append(f"   {format_duration(elapsed_s)}", style="dim")

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
    chip.append(f"   {format_duration(elapsed_s)}", style="dim")
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
    chip.append(f"   {format_duration(elapsed_s)}", style="dim")
    console.print(chip)
    for line in message.split("\n")[:8]:
        if line.strip():
            console.print(Text(f"    {line}", style="dim"))
    console.print()


def _commit_line(c: CommitInfo, *, show_files: bool) -> Text:
    """Format a single commit line with SHA + message + file/insertion/deletion stats."""
    line = Text("  ")
    line.append(f"  {c.sha} ", style="cyan dim")
    line.append(c.message, style="dim")
    if show_files:
        detail = f" ({len(c.files)} {_plural(len(c.files), 'file')}, +{c.insertions}"
        if c.deletions:
            detail += f", -{c.deletions}"
        detail += ")"
        line.append(detail, style="dim")
    return line


def _commit_stat_line(files: int, insertions: int, deletions: int, *, bold: bool = False) -> Text:
    """Format a stat line with files/insertions/deletions counts."""
    label_style = "dim bold" if bold else "dim"
    stat = Text("  ")
    prefix = "  Total: " if bold else "  "
    stat.append(
        f"{prefix}{files} {_plural(files, 'file')} changed",
        style=label_style,
    )
    if insertions:
        stat.append(
            f", {insertions} {_plural(insertions, 'insertion')}(+)",
            style="green dim",
        )
    if deletions:
        stat.append(
            f", {deletions} {_plural(deletions, 'deletion')}(-)",
            style="red dim",
        )
    return stat


def render_phase_commits(phase_result: PhaseResult) -> None:
    """Render a detailed commit summary after an implementing/fixing phase.

    Shows all commits made by the agent during the phase, plus any
    auto-committed leftovers. Replaces the old single-diff display.
    """
    commits = phase_result.commits
    if not commits and not phase_result.uncommitted_changes:
        return

    if len(commits) == 1:
        c = commits[0]
        console.print(_commit_line(c, show_files=False))
        console.print(_commit_stat_line(len(c.files), c.insertions, c.deletions))
    elif len(commits) > 1:
        for c in commits:
            console.print(_commit_line(c, show_files=True))
        total_ins = sum(c.insertions for c in commits)
        total_del = sum(c.deletions for c in commits)
        total_files = len(phase_result.files_changed)
        console.print(_commit_stat_line(total_files, total_ins, total_del, bold=True))

    console.print()


def _render_cost_by_model(snapshots: list[PhaseSnapshot]) -> Text | None:
    """Build the cost-by-model breakdown line for the summary panel.

    Returns ``None`` when no per-phase cost data is available.
    """
    model_costs: dict[str, float] = {}
    for snap in snapshots:
        tier = snap.model or "unknown"
        model_costs[tier] = model_costs.get(tier, 0.0) + snap.cost_usd
    if not model_costs:
        return None

    cost_parts = Text()
    for i, (tier, cost) in enumerate(sorted(model_costs.items(), key=lambda x: -x[1])):
        if i > 0:
            cost_parts.append(", ", style="dim")
        style = MODEL_STYLES.get(tier, "white bold")
        cost_parts.append(tier, style=style)
        cost_parts.append(f" {format_cost(cost)}", style="dim")
    return cost_parts


def _render_pr_or_branch(
    pr_url: str | None, branch: str, feature: Feature,
) -> Text:
    """Build the trailing PR-link line, or a branch hint when no PR exists."""
    if pr_url:
        link = Text()
        link.append("🔗 ", style="green")
        link.append(pr_url, style="blue underline")
        if feature.metadata.linear_issue_key:
            link.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style="cyan")
        return link

    hint = Text()
    hint.append("branch: ", style="dim")
    hint.append(branch, style="dim")
    if feature.metadata.linear_issue_key:
        hint.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style="cyan")
    return hint


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

    grid.add_row("Duration", format_duration(totals.duration_s))
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

    cost_parts = _render_cost_by_model(totals.phase_snapshots)
    if cost_parts is not None:
        grid.add_row("Cost by model", cost_parts)

    rows: list[Text | Table] = [grid, Text()]

    if cost_budget and cost_budget > 0:
        ratio = totals.cost_usd / cost_budget
        rows.append(_budget_row("Cost    ", _bar(ratio), format_cost(totals.cost_usd),
                                f"/ {format_cost(cost_budget)}", f"{int(ratio * 100)}%"))

    rows.append(Text())
    rows.append(phase_dots)

    rows.append(Text())
    rows.append(_render_pr_or_branch(pr_url, branch, feature))

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
    """Compose one cost-budget row: label, progress bar, value, target, and percent."""
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
            format_duration(elapsed) if elapsed else "—",
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


def _flush_stdin_buffer() -> None:
    """Drop any buffered keystrokes accumulated during the previous phase.

    POSIX-only; silently no-ops on Windows or non-tty environments.
    """
    try:
        import termios
    except ImportError:  # pragma: no cover - Windows fallback
        return
    with contextlib.suppress(termios.error, ValueError, OSError):
        termios.tcflush(sys.stdin, termios.TCIFLUSH)


def render_plan_confirmation(plan_output: str, feature_id: str, create_pr: bool) -> bool:
    """Display the plan and prompt for confirmation. Returns True to proceed."""
    console.print()
    console.print(Panel(
        Markdown(plan_output),
        title="Plan proposé",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    _flush_stdin_buffer()

    confirm = console.input(
        "[bold]Lancer l'implémentation ? [Y/n] [/bold]"
    ).strip().lower()
    if confirm and confirm not in ("y", "yes", "o", "oui"):
        console.print()
        console.print("[yellow]Build en pause.[/yellow]")
        console.print(f"[dim]Le plan est sauvegardé dans {feature_id}.[/dim]")
        if create_pr:
            console.print()
            console.print("[bold]Reprendre avec :[/bold]")
            console.print(
                f'  devflow build "ton feedback ici" --resume {feature_id}'
            )
        return False
    return True


def render_doctor_report(report: GateReport) -> None:
    """Display the doctor diagnostic report using Rich."""
    lines = Text()
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        style = "green" if check.passed else "red"
        lines.append(f"  {icon} ", style=style)
        lines.append(f"{check.name}: ", style="bold")
        lines.append(f"{check.message}\n", style=style)
        if check.details:
            lines.append(f"    {check.details[:500]}\n", style="dim")

    verdict = "HEALTHY" if report.passed else "ISSUES FOUND"
    border = "green" if report.passed else "red"

    console.print(Panel(lines, title=f"Doctor — {verdict}", border_style=border))
