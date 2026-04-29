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

from devflow.core.console import console, is_quiet
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
from devflow.ui import theme
from devflow.ui.theme import m as _m


def _plural(n: int, word: str) -> str:
    """Return ``word`` with an 's' appended when ``n`` is not 1."""
    return f"{word}{'s' if n != 1 else ''}"


STACK_ICONS: dict[str, str] = {
    "python": "🐍",
    "typescript": "🟦",
    "php": "🐘",
    "javascript": "🟨",
}

PHASE_DOT_COLORS: dict[str, str] = {
    "done": theme.PHASE_DONE,
    "failed": theme.PHASE_FAILED,
    "in_progress": theme.PHASE_ACTIVE,
    "pending": theme.PHASE_PENDING,
    "skipped": theme.PHASE_SKIPPED,
}


def _model_badge(model: str) -> Text:
    """Colored pill-style label for a Claude model tier."""
    style = theme.MODEL_STYLES.get(model, f"{theme.TEXT} bold")
    return Text(f" {model} ", style=f"reverse {style}", end="")


def _bar(ratio: float, width: int = 24) -> Text:
    """Unicode progress bar. Color shifts from green → yellow → red."""
    ratio = max(0.0, min(1.0, ratio))
    filled = int(width * ratio)
    if ratio < 0.6:
        color = theme.SUCCESS
    elif ratio < 0.85:
        color = theme.WARNING
    else:
        color = theme.ERROR
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style=theme.TEXT_MUTED)
    return bar


def render_build_banner(feature: Feature, branch: str, stack: str | None) -> None:
    """Render the banner shown at the start of a build."""
    if is_quiet():
        return
    stack_label = (stack or "generic").lower()
    icon = STACK_ICONS.get(stack_label, "📦")
    total_phases = len(feature.phases)

    title = Text(feature.description, style=f"bold {theme.TEXT}")
    meta = Text()
    meta.append(feature.id, style=theme.TEXT_MUTED)
    meta.append("  ·  ", style=theme.SEPARATOR)
    meta.append(f"{icon} {stack_label}", style=theme.ACCENT)
    meta.append("  ·  ", style=theme.SEPARATOR)
    meta.append(feature.workflow, style=theme.ACCENT)
    meta.append("  ·  ", style=theme.SEPARATOR)
    meta.append(f"{total_phases} phases", style=theme.ACCENT)

    if feature.metadata.linear_issue_key:
        meta.append("  ·  ", style=theme.SEPARATOR)
        meta.append(f"Linear: {feature.metadata.linear_issue_key}", style=theme.ACCENT)

    branch_line = Text()
    branch_line.append("🌿 ", style=theme.SUCCESS)
    branch_line.append(branch, style=theme.TEXT_MUTED)

    content = Group(title, meta, branch_line)
    console.print()
    console.print(Rule(style=theme.ACCENT))
    console.print(content)
    console.print(Rule(style=theme.ACCENT))
    console.print()


def render_phase_header(
    phase_num: int, total: int, phase_name: str, model: str,
) -> None:
    """Header line printed when a phase starts."""
    if is_quiet():
        return
    header = Text()
    header.append("▶ ", style=f"{theme.ACCENT} bold")
    header.append(f"phase {phase_num}/{total} · ", style=theme.TEXT_MUTED)
    header.append(phase_name, style="bold")
    header.append("   ")
    header.append_text(_model_badge(model))
    console.print()
    console.print(header)


def render_phase_success(
    phase_name: str, elapsed_s: float, metrics: PhaseMetrics,
) -> None:
    """One-line summary chip printed when a phase completes successfully."""
    if is_quiet():
        return
    chip = Text("  ")
    chip.append("✓ ", style=f"{theme.SUCCESS} bold")
    chip.append(phase_name, style="bold")
    chip.append(f"   {format_duration(elapsed_s)}", style=theme.TEXT_MUTED)

    if metrics.tool_count:
        chip.append(f"   {metrics.tool_count} tools", style=theme.TEXT_MUTED)

    if metrics.cost_usd:
        chip.append(f"   {format_cost(metrics.cost_usd)}", style=theme.COST)

    cache_rate = compute_cache_hit_rate(
        metrics.input_tokens, metrics.cache_creation, metrics.cache_read,
    )
    if cache_rate > 0:
        pct = int(cache_rate * 100)
        chip.append(f"   cache {pct}%", style=theme.CACHE_GOOD if pct >= 80 else theme.CACHE_LOW)

    console.print(chip)
    console.print()


def render_phase_failure(phase_name: str, elapsed_s: float, message: str) -> None:
    """One-line failure chip for a phase."""
    if is_quiet():
        return
    chip = Text("  ")
    chip.append("✗ ", style=f"{theme.ERROR} bold")
    chip.append(phase_name, style="bold")
    chip.append(f"   {format_duration(elapsed_s)}", style=theme.TEXT_MUTED)
    console.print(chip)
    for line in message.split("\n")[:5]:
        if line.strip():
            console.print(Text(f"    {line}", style=theme.TEXT_MUTED))
    console.print()


def render_phase_auto_retry(phase_name: str, elapsed_s: float, message: str) -> None:
    """Distinct chip used when a failing gate is about to be auto-retried."""
    if is_quiet():
        return
    chip = Text("  ")
    chip.append("↻ ", style=f"{theme.WARNING} bold")
    chip.append(f"{phase_name} failed — auto-retrying via fixing", style=theme.WARNING)
    chip.append(f"   {format_duration(elapsed_s)}", style=theme.TEXT_MUTED)
    console.print(chip)
    for line in message.split("\n")[:8]:
        if line.strip():
            console.print(Text(f"    {line}", style=theme.TEXT_MUTED))
    console.print()


def _commit_line(c: CommitInfo, *, show_files: bool) -> Text:
    """Format a single commit line with SHA + message + file/insertion/deletion stats."""
    line = Text("  ")
    line.append(f"  {c.sha} ", style=theme.COMMIT_SHA)
    line.append(c.message, style=theme.TEXT_MUTED)
    if show_files:
        detail = f" ({len(c.files)} {_plural(len(c.files), 'file')}, +{c.insertions}"
        if c.deletions:
            detail += f", -{c.deletions}"
        detail += ")"
        line.append(detail, style=theme.TEXT_MUTED)
    return line


def _commit_stat_line(files: int, insertions: int, deletions: int, *, bold: bool = False) -> Text:
    """Format a stat line with files/insertions/deletions counts."""
    label_style = f"{theme.TEXT_MUTED} bold" if bold else theme.TEXT_MUTED
    stat = Text("  ")
    prefix = "  Total: " if bold else "  "
    stat.append(
        f"{prefix}{files} {_plural(files, 'file')} changed",
        style=label_style,
    )
    if insertions:
        stat.append(
            f", {insertions} {_plural(insertions, 'insertion')}(+)",
            style=theme.INSERTION,
        )
    if deletions:
        stat.append(
            f", {deletions} {_plural(deletions, 'deletion')}(-)",
            style=theme.DELETION,
        )
    return stat


def _render_planning_detail(output: str) -> None:
    """Extract and display plan stats from planning output."""
    lines = output.strip().splitlines()
    prefixes = ("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")
    step_count = sum(1 for ln in lines if ln.strip().startswith(prefixes))
    if step_count:
        console.print(Text(f"    {step_count} steps in plan", style=theme.TEXT_DIM))


def _render_review_detail(output: str) -> None:
    """Extract and display review verdict from review output."""
    lower = output.lower()
    if "approve" in lower:
        verdict = "APPROVED"
        style = theme.SUCCESS
    elif "request_changes" in lower or "request changes" in lower:
        verdict = "REQUEST_CHANGES"
        style = theme.WARNING
    else:
        return
    blocking_prefixes = ("- [BLOCKING]", "- **BLOCKING**", "[BLOCKING]")
    blocking = sum(
        1 for ln in output.splitlines()
        if ln.strip().startswith(blocking_prefixes)
    )
    line = Text(f"    {verdict}", style=style)
    if blocking:
        line.append(f" · {blocking} blocking", style=theme.ERROR)
    console.print(line)


def render_phase_commits(phase_name: str, phase_result: PhaseResult) -> None:
    """Render phase-specific detail after completion."""
    if is_quiet():
        return

    if phase_name == "planning":
        _render_planning_detail(phase_result.output)
        console.print()
        return

    if phase_name == "reviewing":
        _render_review_detail(phase_result.output)
        console.print()
        return

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
            cost_parts.append(", ", style=theme.TEXT_MUTED)
        style = theme.MODEL_STYLES.get(tier, f"{theme.TEXT} bold")
        cost_parts.append(tier, style=style)
        cost_parts.append(f" {format_cost(cost)}", style=theme.TEXT_MUTED)
    return cost_parts


def _render_pr_or_branch(
    pr_url: str | None, branch: str, feature: Feature,
) -> Text:
    """Build the trailing PR-link line, or a branch hint when no PR exists."""
    if pr_url:
        link = Text()
        link.append("🔗 ", style=theme.SUCCESS)
        link.append(pr_url, style=f"{theme.ACCENT_ALT} underline")
        if feature.metadata.linear_issue_key:
            link.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style=theme.ACCENT)
        return link

    hint = Text()
    hint.append("branch: ", style=theme.TEXT_MUTED)
    hint.append(branch, style=theme.TEXT_MUTED)
    if feature.metadata.linear_issue_key:
        hint.append(f"  ·  Linear: {feature.metadata.linear_issue_key}", style=theme.ACCENT)
    return hint


def render_build_summary(
    feature: Feature,
    totals: BuildTotals,
    pr_url: str | None,
    branch: str,
    cost_budget: float | None = None,
) -> None:
    """Final multi-block panel shown when a build completes."""
    if is_quiet():
        return
    phase_dots = _render_phase_timeline(feature, totals)

    grid = Table.grid(expand=False, padding=(0, 2))
    grid.add_column(justify="right", style=theme.TEXT_MUTED)
    grid.add_column()

    grid.add_row("Duration", format_duration(totals.duration_s))
    grid.add_row("Cost", Text(format_cost(totals.cost_usd), style=f"{theme.COST} bold"))
    grid.add_row("Tools", str(totals.tool_count))

    cache_rate = compute_cache_hit_rate(
        totals.input_tokens, totals.cache_creation, totals.cache_read,
    )
    if cache_rate > 0:
        cache_pct = int(cache_rate * 100)
        cache_style = theme.CACHE_GOOD if cache_pct >= 80 else theme.CACHE_LOW
        total_in = totals.input_tokens + totals.cache_creation + totals.cache_read
        cache_text = Text()
        cache_text.append(f"{cache_pct}%", style=cache_style)
        cache_text.append(
            f" ({format_tokens(totals.cache_read)} read / {format_tokens(total_in)} total)",
            style=theme.TEXT_MUTED,
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
        title=Text(" ✓ Build complete ", style=f"reverse {theme.SUCCESS} bold"),
        border_style=theme.SUCCESS,
        padding=(1, 2),
    ))


def _budget_row(
    label: str, bar: Text, value: str, of_value: str, pct: str,
) -> Text:
    """Compose one cost-budget row: label, progress bar, value, target, and percent."""
    row = Text()
    row.append(label, style=theme.TEXT_MUTED)
    row.append_text(bar)
    row.append(f"  {value} {of_value}  ", style=theme.TEXT_MUTED)
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
        color = PHASE_DOT_COLORS.get(phase.status.value, theme.TEXT_MUTED)
        dot = Text(f"● {phase.name}", style=color)
        elapsed = totals.phase_durations.get(phase.name)
        label = Text(
            format_duration(elapsed) if elapsed else "—",
            style=theme.TEXT_MUTED,
        )
        dots.append(dot)
        labels.append(label)

    grid.add_row(*dots)
    grid.add_row(*labels)
    return grid


def render_sync_summary(result: SyncResult) -> None:
    """Render a Rich panel summarising the outcome of ``devflow sync``."""
    prefix = f"[{theme.WARNING}]dry-run[/{theme.WARNING}] " if result.dry_run else ""

    grid = Table.grid(expand=False, padding=(0, 2))
    grid.add_column(justify="right", style=theme.TEXT_MUTED)
    grid.add_column()

    # Branches row.
    branch_text = Text()
    if result.branches_deleted:
        branch_text.append(str(len(result.branches_deleted)), style=f"bold {theme.ERROR}")
        branch_text.append(" deleted", style=theme.TEXT_MUTED)
        branch_text.append(f"  ({', '.join(result.branches_deleted)})", style=theme.TEXT_MUTED)
    else:
        branch_text.append("none", style=theme.TEXT_MUTED)
    grid.add_row("Branches", branch_text)

    # Features row.
    feat_text = Text()
    if result.features_archived:
        feat_text.append(str(len(result.features_archived)), style=f"bold {theme.SUCCESS}")
        feat_text.append(" archived", style=theme.TEXT_MUTED)
        feat_text.append(f"  ({', '.join(result.features_archived)})", style=theme.TEXT_MUTED)
    else:
        feat_text.append("none", style=theme.TEXT_MUTED)
    grid.add_row("Features archived", feat_text)

    # Current branch.
    cb_text = Text(result.current_branch or "—", style=theme.ACCENT)
    grid.add_row("Current branch", cb_text)

    rows: list[Text | Table] = [grid]

    if result.dry_run and result.actions:
        rows.append(Text())
        rows.append(Text("Actions that would run:", style=f"{theme.WARNING} dim"))
        for action in result.actions:
            rows.append(Text(f"  • {action}", style=theme.TEXT_MUTED))

    if result.dry_run:
        title_style = f"reverse {theme.WARNING} bold"
    else:
        title_style = f"reverse {theme.SUCCESS} bold"
    title_label = "⏵ Sync (dry-run)" if result.dry_run else "✓ Sync complete"

    console.print()
    console.print(Panel(
        Group(*rows),
        title=Text(f" {prefix}{title_label} ", style=title_style),
        border_style=theme.WARNING if result.dry_run else theme.SUCCESS,
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
    if is_quiet():
        return True
    console.print()
    console.print(Panel(
        Markdown(plan_output),
        title="Plan proposé",
        border_style=theme.ACCENT,
        padding=(1, 2),
    ))
    console.print()

    _flush_stdin_buffer()

    confirm = console.input(
        "[bold]Lancer l'implémentation ? [Y/n] [/bold]"
    ).strip().lower()
    if confirm and confirm not in ("y", "yes", "o", "oui"):
        console.print()
        console.print(_m(theme.WARNING, "Build en pause."))
        console.print(_m(theme.TEXT_MUTED, f"Le plan est sauvegardé dans {feature_id}."))
        if create_pr:
            console.print()
            console.print("[bold]Reprendre avec :[/bold]")
            console.print(
                f'  devflow build "ton feedback ici" --resume {feature_id}'
            )
        return False
    return True


def render_do_banner(_feature: Feature) -> None:
    """No-op — banner printed early in cli.py before complexity scoring."""


def render_resume_notice(feedback: str) -> None:
    """Notice line printed when a build resumes with user feedback."""
    console.print(
        f"{_m(theme.WARNING, '↻ resumed with feedback:')} "
        f"{_m(theme.TEXT_MUTED, feedback)}\n"
    )


def render_pr_creating() -> None:
    """Status line printed while ``gh pr create`` is in flight."""
    console.print(f"[{theme.TEXT_MUTED}]Creating PR…[/{theme.TEXT_MUTED}]")


def render_pr_failed() -> None:
    """Warning shown when ``gh pr create`` returns no URL."""
    console.print(
        f"[{theme.WARNING}]✗ PR creation failed — gh pr create returned no URL"
        f" — Fix: push the branch manually with git push -u origin HEAD[/{theme.WARNING}]\n"
    )


def render_low_cache_warning(avg_cache: float) -> None:
    """Warn when the prompt cache hit rate has been consistently low."""
    pct = int(avg_cache * 100)
    console.print(
        f"[{theme.WARNING}]⚠ Cache hit rate bas ({pct}%) "
        "sur les 3 derniers builds. "
        f"Les prompts système ont peut-être changé.[/{theme.WARNING}]"
    )


def render_epic_complete(epic_id: str) -> None:
    """Banner shown when the last sub-feature of an epic finishes."""
    console.print(
        f"[{theme.SUCCESS} bold]Epic {epic_id} — all sub-features done![/{theme.SUCCESS} bold]\n"
    )


def render_revert_hint(feature_id: str, initial_sha: str) -> None:
    """Failure-recovery hint after ``devflow do`` aborts a phase."""
    short = initial_sha[:7]
    console.print(f"\n{_m(theme.WARNING, 'Gate failed. Changes are still on your branch.')}")
    console.print(_m(theme.TEXT_MUTED, f"Pour annuler : git reset --hard {short}"))
    retry_hint = f"Pour réessayer : devflow build --retry {feature_id}"
    console.print(_m(theme.TEXT_MUTED, retry_hint) + "\n")


def render_do_success(current_sha: str, initial_sha: str) -> None:
    """Success line printed at the end of ``devflow do``."""
    console.print(
        f"{_m(f'{theme.SUCCESS} bold', 'Done.')} HEAD is now {current_sha}.\n"
        f"{_m(theme.TEXT_MUTED, f'Pour annuler : git reset --hard {initial_sha[:7]}')}\n"
    )


def render_doctor_report(report: GateReport) -> None:
    """Display the doctor diagnostic report using Rich."""
    lines = Text()
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        style = theme.SUCCESS if check.passed else theme.ERROR
        lines.append(f"  {icon} ", style=style)
        lines.append(f"{check.name}: ", style="bold")
        lines.append(f"{check.message}\n", style=style)
        if check.details:
            lines.append(f"    {check.details[:500]}\n", style=theme.TEXT_MUTED)

    verdict = "HEALTHY" if report.passed else "ISSUES FOUND"
    border = theme.SUCCESS if report.passed else theme.ERROR

    console.print(Panel(lines, title=f"Doctor — {verdict}", border_style=border))
