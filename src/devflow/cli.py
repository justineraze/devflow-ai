"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

from typing import Annotated

import typer

from devflow.core.track import get_feature, get_state, list_all_features
from devflow.ui.console import console
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


@app.command()
def status(
    feature_id: Annotated[
        str | None, typer.Argument(help="Feature ID for detailed view")
    ] = None,
    archived: Annotated[
        bool, typer.Option("--archived", help="Include archived features")
    ] = False,
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
        render_status_table(state, include_archived=archived)


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
        str | None, typer.Option("--workflow", "-w", help="Workflow to use (default: auto-detect)")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Build a feature end-to-end using the AI workflow.

    Runs planning first, shows the plan for review, then asks
    for confirmation before implementing.

    When resuming with --resume, the description becomes feedback
    on the previous plan (e.g. "no framework detection, just languages").
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import resume_build, start_build

    if resume:
        feature = resume_build(resume)
        feedback = description  # When resuming, description = feedback.
    else:
        feature = start_build(description, workflow)
        feedback = None

    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(feature, feedback=feedback, verbose=verbose)
    if not success:
        raise typer.Exit(1)


@app.command()
def retry(
    feature_id: Annotated[str, typer.Argument(help="Feature ID to retry")],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Retry a failed feature from its last failed phase."""
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import retry_build

    feature = retry_build(feature_id)
    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(feature, verbose=verbose)
    if not success:
        raise typer.Exit(1)


@app.command()
def fix(
    description: Annotated[str, typer.Argument(help="What to fix")],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Fix a bug using a lightweight workflow (no planning phase)."""
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_fix

    feature = start_fix(description)
    success = execute_build_loop(feature, verbose=verbose)
    if not success:
        raise typer.Exit(1)


@app.command()
def sync(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print actions without mutating anything")
    ] = False,
    keep_artifacts: Annotated[
        bool,
        typer.Option(
            "--keep-artifacts",
            help="Skip archiving .devflow/<feat>/ dirs for merged PRs",
        ),
    ] = False,
) -> None:
    """Post-merge cleanup: switch main, prune branches, archive done features.

    Refuses to run if the working tree is dirty.
    """
    from devflow.orchestration.sync import DirtyWorktreeError, run_sync
    from devflow.ui.rendering import render_sync_summary

    try:
        result = run_sync(dry_run=dry_run, keep_artifacts=keep_artifacts)
    except DirtyWorktreeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from exc

    render_sync_summary(result)


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
