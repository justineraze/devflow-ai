"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from devflow.core.track import get_feature, get_state, list_all_features
from devflow.ui.display import (
    render_feature_detail,
    render_header,
    render_log_detail,
    render_log_table,
    render_status_table,
)

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
def log(
    feature_id: Annotated[
        str | None, typer.Argument(help="Feature ID for detailed view")
    ] = None,
) -> None:
    """Show the history of tracked features."""
    render_header(subtitle="Feature log")

    if feature_id:
        feat = get_feature(feature_id)
        if not feat:
            console.print(f"[red]Feature {feature_id!r} not found.[/red]")
            raise typer.Exit(1)
        render_log_detail(feat)
    else:
        features = list_all_features()
        render_log_table(features)


@app.command()
def build(
    description: Annotated[str, typer.Argument(help="What to build, or feedback when resuming")],
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resume a feature by ID")
    ] = None,
    workflow: Annotated[
        str, typer.Option("--workflow", "-w", help="Workflow to use")
    ] = "standard",
) -> None:
    """Build a feature end-to-end using the AI workflow.

    Runs planning first, shows the plan for review, then asks
    for confirmation before implementing.

    When resuming with --resume, the description becomes feedback
    on the previous plan (e.g. "no framework detection, just languages").
    """
    from devflow.orchestration.build import execute_build_loop, resume_build, start_build

    if resume:
        feature = resume_build(resume)
        feedback = description  # When resuming, description = feedback.
    else:
        feature = start_build(description, workflow)
        feedback = None

    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(feature, feedback=feedback)
    if not success:
        raise typer.Exit(1)


@app.command()
def retry(
    feature_id: Annotated[str, typer.Argument(help="Feature ID to retry")],
) -> None:
    """Retry a failed feature from its last failed phase."""
    from devflow.orchestration.build import execute_build_loop, retry_build

    feature = retry_build(feature_id)
    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(feature)
    if not success:
        raise typer.Exit(1)


@app.command()
def fix(
    description: Annotated[str, typer.Argument(help="What to fix")],
) -> None:
    """Fix a bug using a lightweight workflow (no planning phase)."""
    from devflow.orchestration.build import execute_build_loop, start_fix

    feature = start_fix(description)
    success = execute_build_loop(feature)
    if not success:
        raise typer.Exit(1)


@app.command()
def check() -> None:
    """Run the quality gate (lint, tests, secrets detection)."""
    from devflow.integrations.detect import resolve_stack
    from devflow.integrations.gate import render_gate_report, run_gate

    render_header(subtitle="Quality gate")
    report = run_gate(stack=resolve_stack())
    render_gate_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command()
def install() -> None:
    """Install/sync agents and skills to ~/.claude/."""
    from devflow.setup.install import install_all, render_install_report

    render_header(subtitle="Installing agents & skills")
    result = install_all()
    render_install_report(result)


@app.command()
def update() -> None:
    """Update agents and skills to latest version."""
    from devflow.setup.install import install_all, render_install_report

    render_header(subtitle="Updating agents & skills")
    result = install_all()
    render_install_report(result)
    console.print("[green]Components updated.[/green]")


@app.command()
def doctor() -> None:
    """Run diagnostic checks on the devflow installation."""
    from devflow.setup.doctor import render_doctor_report, run_doctor

    render_header(subtitle="Doctor diagnostic")
    report = run_doctor()
    render_doctor_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the current devflow version."""
    from devflow import __version__

    console.print(f"devflow {__version__}")


@app.command()
def init() -> None:
    """Initialize devflow in the current project."""
    from pathlib import Path

    from devflow.core.workflow import ensure_devflow_dir, load_state, save_state
    from devflow.integrations.detect import detect_stack

    devflow_dir = ensure_devflow_dir()

    stack = detect_stack(Path.cwd())
    state = load_state()
    state.stack = stack
    save_state(state)

    console.print(f"[green]Initialized devflow in {devflow_dir}[/green]")
    if stack:
        console.print(f"[green]Stack detected: {stack}[/green]")
    else:
        console.print("[yellow]No stack detected.[/yellow]")
