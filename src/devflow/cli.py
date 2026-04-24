"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from devflow.orchestration.events import BuildCallbacks

from devflow.core.console import console
from devflow.core.workflow import load_state
from devflow.ui.display import (
    render_feature_detail,
    render_header,
    render_log_detail,
    render_log_table,
    render_metrics_table,
    render_status_table,
)


def _version_callback(value: bool) -> None:
    if value:
        from devflow import __version__

        console.print(f"devflow {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="devflow",
    help="CLI that installs and orchestrates an AI dev environment for Claude Code.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True,
                      help="Show the current devflow version."),
    ] = False,
) -> None:
    """CLI that installs and orchestrates an AI dev environment for Claude Code."""


def _deprecation_hint(old: str, new: str) -> None:
    console.print(f"[yellow]{old} is deprecated, use: {new}[/yellow]")


def _ensure_backend() -> None:
    """Register the default Claude Code backend if none is set."""
    from devflow.core.backend import set_backend
    from devflow.integrations.claude.backend import ClaudeCodeBackend

    set_backend(ClaudeCodeBackend())


class _RichPrompter:
    """Rich-based plan confirmation prompter."""

    def confirm_plan(  # noqa: PLR6301
        self, plan_output: str, feature_id: str, create_pr: bool,
    ) -> bool:
        from devflow.ui.rendering import render_plan_confirmation
        return render_plan_confirmation(plan_output, feature_id, create_pr)


def _build_callbacks() -> BuildCallbacks:
    """Wire up UI renderers as build callbacks (lazy import)."""
    from devflow.orchestration.events import BuildCallbacks
    from devflow.ui.gate_panel import render_gate_panel
    from devflow.ui.rendering import (
        render_build_banner,
        render_build_summary,
        render_do_banner,
        render_do_success,
        render_epic_complete,
        render_low_cache_warning,
        render_phase_auto_retry,
        render_phase_commits,
        render_phase_failure,
        render_phase_header,
        render_phase_success,
        render_pr_creating,
        render_pr_failed,
        render_resume_notice,
        render_revert_hint,
    )

    return BuildCallbacks(
        on_banner=render_build_banner,
        on_do_banner=render_do_banner,
        on_resume_notice=render_resume_notice,
        on_phase_header=render_phase_header,
        on_phase_success=render_phase_success,
        on_phase_failure=render_phase_failure,
        on_phase_auto_retry=render_phase_auto_retry,
        on_phase_commits=render_phase_commits,
        on_gate_panel=render_gate_panel,
        on_build_summary=render_build_summary,
        on_pr_creating=render_pr_creating,
        on_pr_failed=render_pr_failed,
        on_low_cache_warning=render_low_cache_warning,
        on_epic_complete=render_epic_complete,
        on_revert_hint=render_revert_hint,
        on_do_success=render_do_success,
        prompter=_RichPrompter(),
    )


# ---------------------------------------------------------------------------
# status (absorbs log)
# ---------------------------------------------------------------------------

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
    log: Annotated[
        bool, typer.Option("--log", "-l", help="Show phase history (replaces `devflow log`)")
    ] = False,
) -> None:
    """Show the status of tracked features."""
    render_header(subtitle="Feature status")

    if metrics:
        from devflow.core.history import read_history

        records = read_history()
        render_metrics_table(records)
        return

    if log:
        if feature_id:
            feat = load_state().get_feature(feature_id)
            if not feat:
                console.print(f"[red]Feature {feature_id!r} not found.[/red]")
                raise typer.Exit(1)
            render_log_detail(feat)
        else:
            features = list(load_state().features.values())
            render_log_table(features)
        return

    if feature_id:
        feat = load_state().get_feature(feature_id)
        if not feat:
            console.print(f"[red]Feature {feature_id!r} not found.[/red]")
            raise typer.Exit(1)
        render_feature_detail(feat)
    else:
        state = load_state()
        render_status_table(state, include_archived=archived)


# ---------------------------------------------------------------------------
# build (absorbs retry)
# ---------------------------------------------------------------------------

def _resolve_base_branch(override: str | None) -> str:
    """Resolve base branch: CLI flag > config.yaml > 'main'."""
    if override:
        return override
    from devflow.core.config import load_config
    return load_config().base_branch


@app.command()
def build(
    description: Annotated[
        str | None, typer.Argument(help="What to build, or feedback when resuming")
    ] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resume a feature by ID")
    ] = None,
    retry: Annotated[
        str | None, typer.Option("--retry", "-r", help="Retry a failed feature by ID")
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

    With --resume, the description becomes feedback on the previous plan.
    With --retry, retries the last failed phase (no description needed).
    With --worktree, the build runs in a separate git worktree.
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import resume_build, retry_build, start_build

    _ensure_backend()

    if retry and resume:
        console.print("[red]Cannot use --retry and --resume together.[/red]")
        raise typer.Exit(1)

    base_branch = _resolve_base_branch(base)

    if retry:
        feature = retry_build(retry)
        feedback = None
    elif resume:
        if not description:
            console.print("[red]--resume requires a description (feedback on the plan).[/red]")
            raise typer.Exit(1)
        feature = resume_build(resume)
        feedback = description
    else:
        if not description:
            console.print("[red]Missing description. Usage: devflow build \"what to build\"[/red]")
            raise typer.Exit(1)
        feature = start_build(description, workflow)
        feedback = None

    if not feature:
        raise typer.Exit(1)

    success = execute_build_loop(
        feature, feedback=feedback, verbose=verbose,
        base_branch=base_branch, worktree=worktree,
        callbacks=_build_callbacks(),
    )
    if not success:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# do
# ---------------------------------------------------------------------------

@app.command(name="do")
def do_task(
    description: Annotated[str, typer.Argument(help="What to do")],
    workflow: Annotated[
        str | None, typer.Option("--workflow", "-w", help="Workflow to use (default: auto-detect)")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """Task on the current branch — no new branch, no PR.

    Runs the same phases as ``devflow build`` (planning, implementing,
    reviewing, gate…) but stays on the current branch.  The workflow
    is auto-detected from task complexity unless overridden with -w.
    On failure, all commits are reverted automatically.
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_do

    _ensure_backend()
    feature = start_do(description, workflow)
    success = execute_build_loop(
        feature, verbose=verbose, create_pr=False, callbacks=_build_callbacks(),
    )
    if not success:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@app.command()
def check() -> None:
    """Run the quality gate (lint, tests, secrets detection)."""
    from devflow.integrations.detect import resolve_stack
    from devflow.integrations.gate import run_gate
    from devflow.integrations.gate.context import build_context
    from devflow.ui.gate_panel import render_gate_report

    render_header(subtitle="Quality gate")
    ctx = build_context(mode="audit")
    report = run_gate(ctx, stack=resolve_stack())
    render_gate_report(report)
    if not report.passed:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# install (absorbs init + doctor)
# ---------------------------------------------------------------------------

@app.command()
def install(
    check_only: Annotated[
        bool, typer.Option("--check", help="Run diagnostic only, don't install anything")
    ] = False,
    linear_team: Annotated[
        str | None,
        typer.Option("--linear-team", help="Linear team key (e.g. 'ABC') for issue sync"),
    ] = None,
) -> None:
    """Install agents & skills, initialize project, and run diagnostics.

    First run: installs assets to ~/.claude/, detects your stack, sets the
    base branch in state.json.

    Subsequent runs: updates assets, skips init if .devflow/ already exists.

    With --check, only runs the diagnostic (no install or init).
    """
    from devflow.setup.doctor import run_doctor
    from devflow.ui.rendering import render_doctor_report

    if check_only:
        render_header(subtitle="Doctor diagnostic")
        report = run_doctor()
        render_doctor_report(report)
        if not report.passed:
            raise typer.Exit(1)
        return

    from devflow.setup.install import install_all, render_install_report

    render_header(subtitle="Installing agents & skills")
    result = install_all()
    render_install_report(result)

    # --- init: detect stack + base branch → config.yaml ---
    from devflow.core.config import load_config, save_config
    from devflow.core.workflow import ensure_devflow_dir, load_state, save_state
    from devflow.integrations.detect import detect_stack
    from devflow.integrations.git import detect_base_branch

    ensure_devflow_dir()
    config = load_config()

    if not config.stack:
        config.stack = detect_stack(Path.cwd())

    if config.base_branch == "main":
        config.base_branch = detect_base_branch()

    if linear_team is not None:
        config.linear.team = linear_team

    save_config(config)

    # Ensure state.json exists (empty state is fine for first run).
    state = load_state()
    save_state(state)

    if config.stack:
        console.print(f"[green]Stack: {config.stack}[/green]")
    console.print(f"[green]Base branch: {config.base_branch}[/green]")
    if config.linear.team:
        console.print(f"[green]Linear team: {config.linear.team}[/green]")

    # --- doctor ---
    render_header(subtitle="Doctor diagnostic")
    report = run_doctor()
    render_doctor_report(report)


# ---------------------------------------------------------------------------
# Deprecated shims — run the real command after a warning
# ---------------------------------------------------------------------------

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
    """(Deprecated) Use ``devflow do`` or ``devflow build --workflow quick``."""
    _deprecation_hint("fix", "devflow do")
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_fix

    _ensure_backend()
    feature = start_fix(description)
    base_branch = _resolve_base_branch(base)
    success = execute_build_loop(
        feature, verbose=verbose, base_branch=base_branch,
        callbacks=_build_callbacks(),
    )
    if not success:
        raise typer.Exit(1)


@app.command(name="retry", deprecated=True, hidden=True)
def retry_cmd(
    feature_id: Annotated[str, typer.Argument(help="Feature ID to retry")],
    base: Annotated[
        str | None, typer.Option("--base", "-b", help="Base branch for PR (default: from state)")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Stream every tool call instead of spinner")
    ] = False,
) -> None:
    """(Deprecated) Use ``devflow build --retry <feat-id>``."""
    _deprecation_hint("retry", f"devflow build --retry {feature_id}")
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import retry_build

    _ensure_backend()
    feature = retry_build(feature_id)
    if not feature:
        raise typer.Exit(1)

    base_branch = _resolve_base_branch(base)
    success = execute_build_loop(
        feature, verbose=verbose, base_branch=base_branch,
        callbacks=_build_callbacks(),
    )
    if not success:
        raise typer.Exit(1)


@app.command(name="log", deprecated=True, hidden=True)
def log_cmd(
    feature_id: Annotated[
        str | None, typer.Argument(help="Feature ID for detailed view")
    ] = None,
) -> None:
    """(Deprecated) Use ``devflow status --log``."""
    _deprecation_hint("log", "devflow status --log")
    render_header(subtitle="Feature log")

    if feature_id:
        feat = load_state().get_feature(feature_id)
        if not feat:
            console.print(f"[red]Feature {feature_id!r} not found.[/red]")
            raise typer.Exit(1)
        render_log_detail(feat)
    else:
        features = list(load_state().features.values())
        render_log_table(features)



@app.command(name="doctor", deprecated=True, hidden=True)
def doctor_cmd() -> None:
    """(Deprecated) Use ``devflow install --check``."""
    _deprecation_hint("doctor", "devflow install --check")
    from devflow.setup.doctor import run_doctor
    from devflow.ui.rendering import render_doctor_report

    render_header(subtitle="Doctor diagnostic")
    report = run_doctor()
    render_doctor_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command(name="version", deprecated=True, hidden=True)
def version_cmd() -> None:
    """(Deprecated) Use ``devflow --version``."""
    _deprecation_hint("version", "devflow --version")
    from devflow import __version__

    console.print(f"devflow {__version__}")
