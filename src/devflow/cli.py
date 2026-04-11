"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from devflow.display import render_feature_detail, render_header, render_status_table
from devflow.track import get_feature, get_state

app = typer.Typer(
    name="devflow",
    help="CLI that installs and orchestrates an AI dev environment for Claude Code.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def status(
    feature_id: Annotated[
        str | None, typer.Argument(help="Feature ID for detailed view")
    ] = None,
) -> None:
    """Show the status of tracked features."""
    render_header(subtitle="Feature status")

    if feature_id:
        feat = get_feature(feature_id)
        if not feat:
            console.print(f"[red]Feature {feature_id!r} not found.[/red]")
            raise typer.Exit(1)
        render_feature_detail(feat)
    else:
        state = get_state()
        render_status_table(state)


@app.command()
def build(
    description: Annotated[str, typer.Argument(help="What to build")],
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resume a feature by ID")
    ] = None,
    workflow: Annotated[
        str, typer.Option("--workflow", "-w", help="Workflow to use")
    ] = "standard",
) -> None:
    """Build a feature end-to-end using the AI workflow."""
    from devflow.build import resume_build, run_phase, start_build

    feature = resume_build(resume) if resume else start_build(description, workflow)

    if not feature:
        raise typer.Exit(1)

    # Run all phases sequentially.
    while not feature.is_terminal:
        phase = run_phase(feature)
        if not phase:
            break
        # In a real run, this is where Claude Code executes the phase.
        # For now, we mark phases as done to advance the state machine.
        console.print(
            f"[dim]→ Phase {phase.name!r} ready for agent execution[/dim]"
        )
        break  # Stop after preparing one phase — Claude Code takes over.


@app.command()
def fix(
    description: Annotated[str, typer.Argument(help="What to fix")],
) -> None:
    """Fix a bug using a lightweight workflow (no planning phase)."""
    from devflow.build import start_fix

    feature = start_fix(description)
    console.print(f"[green]Fix started:[/green] {feature.id}")
    console.print("[dim]Workflow: quick (implement → gate)[/dim]")


@app.command()
def check() -> None:
    """Run the quality gate (lint, tests, secrets detection)."""
    from devflow.gate import render_gate_report, run_gate

    render_header(subtitle="Quality gate")
    report = run_gate()
    render_gate_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command()
def install() -> None:
    """Install/sync agents and skills to ~/.claude/."""
    from devflow.install import install_all, render_install_report

    render_header(subtitle="Installing agents & skills")
    result = install_all()
    render_install_report(result)


@app.command()
def update() -> None:
    """Update agents and skills to latest version."""
    from devflow.install import install_all, render_install_report

    render_header(subtitle="Updating agents & skills")
    result = install_all()
    render_install_report(result)
    console.print("[green]Components updated.[/green]")


@app.command()
def init() -> None:
    """Initialize devflow in the current project."""
    from devflow.workflow import ensure_devflow_dir

    devflow_dir = ensure_devflow_dir()
    console.print(f"[green]Initialized devflow in {devflow_dir}[/green]")
