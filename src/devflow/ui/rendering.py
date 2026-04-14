"""Rich renderers for the build flow — banner, phase headers, summaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from devflow.core.models import Feature
from devflow.orchestration.stream import PhaseMetrics, format_cost, format_tokens

console = Console()

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


@dataclass
class BuildTotals:
    """Running totals across all phases of a build."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    tool_count: int = 0
    duration_s: float = 0.0
    phase_durations: dict[str, float] = field(default_factory=dict)

    def add(self, phase_name: str, metrics: PhaseMetrics, elapsed_s: float) -> None:
        self.cost_usd += metrics.cost_usd
        self.input_tokens += metrics.input_tokens
        self.output_tokens += metrics.output_tokens
        self.cache_read += metrics.cache_read
        self.tool_count += metrics.tool_count
        self.duration_s += elapsed_s
        self.phase_durations[phase_name] = elapsed_s


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

    if metrics.input_tokens or metrics.output_tokens:
        chip.append("   ")
        chip.append(format_tokens(metrics.input_tokens), style="cyan")
        chip.append(" in", style="dim")
        if metrics.cache_read:
            chip.append(f" (cache {format_tokens(metrics.cache_read)})", style="dim")
        chip.append(" / ", style="dim")
        chip.append(format_tokens(metrics.output_tokens), style="cyan")
        chip.append(" out", style="dim")

    if metrics.cost_usd:
        chip.append(f"   {format_cost(metrics.cost_usd)}", style="yellow")

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


def render_build_summary(
    feature: Feature,
    totals: BuildTotals,
    pr_url: str | None,
    branch: str,
    cost_budget: float | None = None,
    context_budget: int = 200_000,
) -> None:
    """Final multi-block panel shown when a build completes."""
    phase_dots = _render_phase_timeline(feature, totals)

    grid = Table.grid(expand=False, padding=(0, 2))
    grid.add_column(justify="right", style="dim")
    grid.add_column()

    grid.add_row("Duration", _fmt_duration(totals.duration_s))
    grid.add_row("Cost", Text(format_cost(totals.cost_usd), style="yellow bold"))
    grid.add_row("Tools", str(totals.tool_count))

    in_text = Text()
    in_text.append(format_tokens(totals.input_tokens), style="cyan")
    if totals.cache_read:
        in_text.append(f" (cache {format_tokens(totals.cache_read)})", style="dim")
    in_text.append(" in · ", style="dim")
    in_text.append(format_tokens(totals.output_tokens), style="cyan")
    in_text.append(" out", style="dim")
    grid.add_row("Tokens", in_text)

    rows: list = [grid, Text()]

    if cost_budget and cost_budget > 0:
        ratio = totals.cost_usd / cost_budget
        rows.append(_budget_row("Cost    ", _bar(ratio), format_cost(totals.cost_usd),
                                f"/ {format_cost(cost_budget)}", f"{int(ratio * 100)}%"))

    total_tokens = totals.input_tokens + totals.cache_read
    ctx_ratio = total_tokens / context_budget if context_budget else 0
    rows.append(_budget_row("Context ", _bar(ctx_ratio),
                            format_tokens(total_tokens),
                            f"/ {format_tokens(context_budget)}",
                            f"{int(ctx_ratio * 100)}%"))

    rows.append(Text())
    rows.append(phase_dots)

    if pr_url:
        rows.append(Text())
        link = Text()
        link.append("🔗 ", style="green")
        link.append(pr_url, style="blue underline")
        rows.append(link)
    else:
        rows.append(Text())
        hint = Text()
        hint.append("branch: ", style="dim")
        hint.append(branch, style="dim")
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


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{int(round(seconds))}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"
