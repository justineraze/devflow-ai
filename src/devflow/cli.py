"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

from typing import Annotated

import typer

from devflow.core.console import console
from devflow.core.track import get_feature, get_state, list_all_features
from devflow.ui.display import (
    render_feature_detail,
    render_header,
    render_log_detail,
    render_log_table,
    render_metrics_table,
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
    metrics: Annotated[
        bool, typer.Option("--metrics", "-m", help="Show build cost/token history")
    ] = False,
) -> None:
    """Show the status of tracked features."""
    render_header(subtitle="Feature status")

    if metrics:
        from devflow.core.history import read_history

        records = read_history()
        render_metrics_table(records)
        return

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


def _resolve_base_branch(override: str | None) -> str:
    """Resolve base branch: CLI flag > state.json > "main"."""
    if override:
        return override
    state = get_state()
    return state.base_branch


@app.command()
def build(
    description: Annotated[str, typer.Argument(help="What to build, or feedback when resuming")],
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resume a feature by ID")
    ] = None,
    workflow: Annotated[
        str | None, typer.Option("--workflow", "-w", help="Workflow to use (default: auto-detect)")
    ] = None,
    base: Annotated[
        str | None, typer.Option("--base", "-b", help="Base branch for PR (default: from state)")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
    worktree: Annotated[
        bool, typer.Option("--worktree", "-W", help="Run in an isolated git worktree")
    ] = False,
) -> None:
    """Build a feature end-to-end using the AI workflow.

    Runs planning first, shows the plan for review, then asks
    for confirmation before implementing.

    When resuming with --resume, the description becomes feedback
    on the previous plan (e.g. "no framework detection, just languages").

    With --worktree, the build runs in a separate git worktree under
    .devflow/.worktrees/, allowing multiple builds in parallel.
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import resume_build, start_build

    base_branch = _resolve_base_branch(base)

    if resume:
        feature = resume_build(resume)
        feedback = description  # When resuming, description = feedback.
    else:
        feature = start_build(description, workflow)
        feedback = None

    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(
        feature, feedback=feedback, verbose=verbose,
        base_branch=base_branch, worktree=worktree,
    )
    if not success:
        raise typer.Exit(1)


@app.command()
def retry(
    feature_id: Annotated[str, typer.Argument(help="Feature ID to retry")],
    base: Annotated[
        str | None, typer.Option("--base", "-b", help="Base branch for PR (default: from state)")
    ] = None,
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

    base_branch = _resolve_base_branch(base)
    success = execute_build_loop(feature, verbose=verbose, base_branch=base_branch)
    if not success:
        raise typer.Exit(1)


@app.command(name="do")
def do_task(
    description: Annotated[str, typer.Argument(help="What to do")],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Quick task on the current branch — single commit, revertable.

    Stays on the current branch (no new branch, no PR).
    Runs implementing → gate. If the gate fails after retries,
    the commit is automatically reverted.
    """
    from devflow.orchestration.build import execute_do_loop
    from devflow.orchestration.lifecycle import start_do

    feature = start_do(description)
    success = execute_do_loop(feature, verbose=verbose)
    if not success:
        raise typer.Exit(1)


@app.command(deprecated=True)
def fix(
    description: Annotated[str, typer.Argument(help="What to fix")],
    base: Annotated[
        str | None, typer.Option("--base", "-b", help="Base branch for PR (default: from state)")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Fix a bug using a lightweight workflow (no planning phase).

    Deprecated: use ``devflow do`` for quick tasks on the current branch,
    or ``devflow build --workflow quick`` for a full build with PR.
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_fix

    feature = start_fix(description)
    base_branch = _resolve_base_branch(base)
    success = execute_build_loop(feature, verbose=verbose, base_branch=base_branch)
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
    linear: Annotated[
        bool,
        typer.Option("--linear", help="Sync feature statuses to Linear"),
    ] = False,
) -> None:
    """Post-merge cleanup: switch main, prune branches, archive done features.

    With --linear, also syncs feature statuses to Linear issues
    (requires LINEAR_API_KEY and devflow init --linear-team).

    Refuses to run if the working tree is dirty.
    """
    if linear:
        from devflow.integrations.linear.sync import sync_all

        result = sync_all()
        if result.errors:
            for err in result.errors:
                console.print(f"[red]✗ {err}[/red]")
            raise typer.Exit(1)
        if result.created:
            console.print(f"[green]Created {len(result.created)} issues[/green]")
        if result.updated:
            console.print(f"[green]Updated {len(result.updated)} issues[/green]")
        if not result.created and not result.updated:
            console.print("[dim]Nothing to sync.[/dim]")
        return

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
    from devflow.integrations.gate import run_gate
    from devflow.ui.gate_panel import render_gate_report

    render_header(subtitle="Quality gate")
    report = run_gate(stack=resolve_stack())
    render_gate_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command()
def install() -> None:
    """Install or update agents and skills to ~/.claude/."""
    from devflow.setup.install import install_all, render_install_report

    render_header(subtitle="Installing agents & skills")
    result = install_all()
    render_install_report(result)


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
def init(
    linear_team: Annotated[
        str | None,
        typer.Option("--linear-team", help="Linear team key (e.g. 'ABC') for issue sync"),
    ] = None,
) -> None:
    """Initialize devflow in the current project."""
    from pathlib import Path

    from devflow.core.workflow import ensure_devflow_dir, load_state, save_state
    from devflow.integrations.detect import detect_stack
    from devflow.integrations.git import detect_base_branch

    devflow_dir = ensure_devflow_dir()

    stack = detect_stack(Path.cwd())
    base_branch = detect_base_branch()
    state = load_state()
    state.stack = stack
    state.base_branch = base_branch
    if linear_team is not None:
        state.linear_team_id = linear_team
    save_state(state)

    console.print(f"[green]Initialized devflow in {devflow_dir}[/green]")
    if stack:
        console.print(f"[green]Stack detected: {stack}[/green]")
    else:
        console.print("[yellow]No stack detected.[/yellow]")
    console.print(f"[green]Base branch: {base_branch}[/green]")
    if state.linear_team_id:
        console.print(f"[green]Linear team: {state.linear_team_id}[/green]")
