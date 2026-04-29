"""CLI commands — Typer entry points, zero business logic."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from contextlib import contextmanager
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
    render_metrics_dashboard,
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
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q", help="Minimal output, no Rich formatting",
        ),
    ] = False,
) -> None:
    """CLI that installs and orchestrates an AI dev environment for Claude Code."""
    import devflow.core.console as console_mod

    console_mod.quiet = quiet
    _boot_logging()


@app.command()
def init(
    stack: Annotated[
        str | None,
        typer.Option("--stack", help="Stack: python / typescript / php / frontend / auto-detect"),
    ] = None,
    base_branch: Annotated[
        str | None,
        typer.Option("--base-branch", help="Base branch for PRs (default: auto-detect)"),
    ] = None,
    backend: Annotated[
        str | None,
        typer.Option("--backend", help="AI backend: claude / pi"),
    ] = None,
    no_tracker: Annotated[
        bool,
        typer.Option("--no-tracker", help="Skip issue tracker setup"),
    ] = False,
    linear_team: Annotated[
        str | None,
        typer.Option("--linear-team", help="Linear team ID"),
    ] = None,
    gate_lint: Annotated[
        str | None,
        typer.Option("--gate-lint", help="Custom lint command"),
    ] = None,
    gate_test: Annotated[
        str | None,
        typer.Option("--gate-test", help="Custom test command"),
    ] = None,
) -> None:
    """Initialize a devflow project — interactive wizard or scripted via flags.

    Examples:
      devflow init
      devflow init --stack python --base-branch main --backend claude --no-tracker
      devflow init --stack auto-detect --linear-team ABC
    """
    from devflow.integrations.detect import detect_stack
    from devflow.integrations.git import detect_base_branch
    from devflow.setup.init import run_init_wizard

    config = run_init_wizard(
        stack=stack,
        base_branch=base_branch,
        backend=backend,
        no_tracker=no_tracker,
        linear_team=linear_team,
        gate_lint=gate_lint,
        gate_test=gate_test,
        detect_stack_fn=detect_stack,
        detect_base_branch_fn=detect_base_branch,
    )

    if config.stack:
        console.print(f"[green]Stack: {config.stack}[/green]")
    console.print(f"[green]Base branch: {config.base_branch}[/green]")
    if config.linear.team:
        console.print(f"[green]Linear team: {config.linear.team}[/green]")

    # Suggest install if not done
    from devflow.setup.doctor import check_agents_synced

    agents_check = check_agents_synced()
    if not agents_check.passed:
        console.print("\n[yellow]Run `devflow install` to sync agents & skills.[/yellow]")

    # Boot backend so doctor can check availability
    _ensure_backend()

    # Run doctor
    from devflow.setup.doctor import run_doctor
    from devflow.ui.rendering import render_doctor_report

    console.print()
    report = run_doctor()
    render_doctor_report(report)


def _deprecation_hint(old: str, new: str) -> None:
    console.print(f"[yellow]{old} is deprecated, use: {new}[/yellow]")


def _boot_logging() -> None:
    """Configure structured logging (call once at CLI boot)."""
    from devflow.core.logging import setup_logging

    setup_logging()


def _ensure_backend(override: str | None = None) -> None:
    """Register both backends and activate the requested one."""
    from devflow.core.config import load_config
    from devflow.core.registry import (
        discover_trackers,
        register_backend,
        set_active_backend,
    )
    from devflow.integrations.claude.backend import ClaudeCodeBackend

    register_backend("claude", ClaudeCodeBackend())

    try:
        from devflow.integrations.pi.backend import PiBackend

        register_backend("pi", PiBackend())
    except Exception:
        pass

    config = load_config()
    backend_name = override or config.backend
    try:
        set_active_backend(backend_name)
    except RuntimeError:
        set_active_backend("claude")

    discover_trackers()


class _RichPrompter:
    """Rich-based plan confirmation prompter."""

    def confirm_plan(  # noqa: PLR6301
        self, plan_output: str, feature_id: str, create_pr: bool,
    ) -> bool:
        from devflow.ui.rendering import render_plan_confirmation
        return render_plan_confirmation(plan_output, feature_id, create_pr)


@contextmanager
def _spinner_phase_listener(
    phase_name: str,
) -> Generator[Callable[[object], None] | None, None, None]:
    """Yield a spinner-update callback for one phase execution.

    Wired into ``BuildCallbacks.phase_tool_listener`` so the runner stays
    UI-agnostic — see :mod:`devflow.orchestration.events` for the
    contract.
    """
    from devflow.core.metrics import ToolUse
    from devflow.ui.spinner import PhaseSpinner

    with PhaseSpinner(phase_name) as spinner:
        def _on_tool(tool: object) -> None:
            if isinstance(tool, ToolUse):
                spinner.update(tool.name, tool.summary)
        yield _on_tool


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
        phase_tool_listener=_spinner_phase_listener,
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
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON (for scripting)")
    ] = False,
) -> None:
    """Show the status of tracked features.

    Examples:
      devflow status
      devflow status feat-042
      devflow status --archived
      devflow status --json | jq '.features[] | select(.status == "implementing")'
    """
    if json_output:
        import json as json_mod

        state = load_state()
        features = list(state.features.values())
        if not archived:
            features = [f for f in features if not f.metadata.archived]

        if feature_id:
            feat = state.get_feature(feature_id)
            if not feat:
                console.print(json_mod.dumps({"error": f"Feature {feature_id!r} not found"}))
                raise typer.Exit(1)
            console.print(json_mod.dumps(feat.model_dump(mode="json"), indent=2))
            return

        data = {
            "features": [
                {
                    "id": f.id,
                    "status": f.status.value,
                    "description": f.description,
                    "workflow": f.workflow,
                    "worktree": f.metadata.worktree_path,
                }
                for f in features
            ],
            "active_count": sum(
                1 for f in features if f.status.value not in ("done", "archived")
            ),
            "done_count": sum(1 for f in features if f.status.value == "done"),
        }
        console.print(json_mod.dumps(data, indent=2))
        return

    render_header(subtitle="Feature status")

    if metrics:
        _deprecation_hint("--metrics", "devflow metrics")
        from devflow.core.history import read_history

        records = read_history()
        render_metrics_table(records)
        return

    if log:
        if feature_id:
            feat = load_state().get_feature(feature_id)
            if not feat:
                console.print(
                    f"[red]✗ Feature {feature_id!r} not found — not in state.json"
                    " — Fix: run devflow status to list features[/red]"
                )
                raise typer.Exit(1)
            render_log_detail(feat)
        else:
            features = list(load_state().features.values())
            render_log_table(features)
        return

    if feature_id:
        feat = load_state().get_feature(feature_id)
        if not feat:
            console.print(
                f"[red]✗ Feature {feature_id!r} not found — not in state.json"
                " — Fix: run devflow status to list features[/red]"
            )
            raise typer.Exit(1)
        render_feature_detail(feat)
    else:
        state = load_state()
        render_status_table(state, include_archived=archived)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

@app.command()
def metrics(
    since: Annotated[
        str | None, typer.Option("--since", "-s", help="Time window (e.g. 7d, 2w)")
    ] = None,
    export: Annotated[
        str | None, typer.Option("--export", "-e", help="Export format (json)")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON (alias for --export json)")
    ] = False,
) -> None:
    """Show build metrics dashboard with KPIs.

    Examples:
      devflow metrics
      devflow metrics --since 7d
      devflow metrics --json
      devflow metrics --export json
    """
    import json as json_mod

    if json_output:
        export = "json"

    from devflow.core.config import load_config
    from devflow.core.history import read_phase_records
    from devflow.core.kpis import compute_dashboard, parse_since

    since_dt = None
    if since:
        try:
            since_dt = parse_since(since)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

    config = load_config()
    budget = config.budget.per_feature_usd
    records = read_phase_records()
    dashboard = compute_dashboard(records, since=since_dt, budget_per_feature=budget)

    if export == "json":
        from dataclasses import asdict
        data = asdict(dashboard)
        data.pop("budget_warnings", None)
        console.print(json_mod.dumps(data, indent=2))
        return

    render_header(subtitle="Metrics dashboard")
    render_metrics_dashboard(dashboard)


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
    backend: Annotated[
        str | None, typer.Option("--backend", help="AI backend override (claude | pi)")
    ] = None,
) -> None:
    """Build a feature end-to-end using the AI workflow.

    Runs planning first, shows the plan for review, then asks
    for confirmation before implementing.

    With --resume, the description becomes feedback on the previous plan.
    With --retry, retries the last failed phase (no description needed).
    With --worktree, the build runs in a separate git worktree.

    Examples:
      devflow build "add user authentication"
      devflow build "fix payment timeout" --backend pi
      devflow build --resume feat-042 "focus on error handling"
      devflow build --retry feat-042
      devflow build "refactor DB layer" --worktree
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import resume_build, retry_build, start_build

    _ensure_backend(backend)

    if retry and resume:
        console.print(
            "[red]✗ Conflicting flags — --retry and --resume cannot be used together"
            " — Fix: use one or the other[/red]"
        )
        raise typer.Exit(1)

    base_branch = _resolve_base_branch(base)

    from devflow.core.errors import DevflowError

    try:
        if retry:
            feature = retry_build(retry)
            feedback = None
        elif resume:
            if not description:
                console.print(
                    f"[red]✗ Missing feedback — --resume requires a description"
                    f" — Fix: devflow build \"your feedback\" --resume {resume}[/red]"
                )
                raise typer.Exit(1)
            feature = resume_build(resume)
            feedback = description
        else:
            if not description:
                console.print(
                    "[red]✗ Missing description — devflow build needs a task"
                    " — Fix: devflow build \"what to build\"[/red]"
                )
                raise typer.Exit(1)
            feature = start_build(description, workflow)
            feedback = None
    except DevflowError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if feature.metadata.linear_issue_key:
        console.print(f"[dim]Linear: {feature.metadata.linear_issue_key}[/dim]")

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
    backend: Annotated[
        str | None, typer.Option("--backend", help="AI backend override (claude | pi)")
    ] = None,
) -> None:
    """Task on the current branch — no new branch, no PR.

    Runs the same phases as build but stays on the current branch.
    On failure, changes stay on branch (user decides).

    Examples:
      devflow do "fix typo in README"
      devflow do "add input validation" --workflow standard
      devflow do "refactor utils" --verbose
    """
    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_do

    console.print(f"\n[bold]do:[/bold] {description[:80]}\n")
    _ensure_backend(backend)
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
def check(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON (for scripting)")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show per-check timing")
    ] = False,
) -> None:
    """Run the quality gate (lint, tests, secrets detection).

    Examples:
      devflow check
      devflow check --verbose
      devflow check --json
      devflow check --json | jq '.checks[] | select(.passed == false)'
    """
    from devflow.integrations.detect import resolve_stack
    from devflow.integrations.gate import run_gate
    from devflow.integrations.gate.context import build_context

    ctx = build_context(mode="audit")
    report = run_gate(ctx, stack=resolve_stack())

    if json_output:
        import json as json_mod

        console.print(json_mod.dumps(report.to_dict(), indent=2))
        if not report.passed:
            raise typer.Exit(1)
        return

    from devflow.ui.gate_panel import render_gate_report

    render_header(subtitle="Quality gate")
    render_gate_report(report, verbose=verbose)
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
    prune_orphans: Annotated[
        bool,
        typer.Option(
            "--prune-orphans",
            help="Also delete feat/* branches with 0 commits ahead of main",
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

    Examples:
      devflow sync
      devflow sync --dry-run
      devflow sync --prune-orphans
      devflow sync --linear
    """
    if linear:
        from devflow.integrations.linear.sync import sync_all

        linear_result = sync_all()
        if linear_result.errors:
            for err in linear_result.errors:
                console.print(f"[red]✗ {err}[/red]")
            raise typer.Exit(1)
        if linear_result.created:
            console.print(f"[green]Created {len(linear_result.created)} issues[/green]")
        if linear_result.updated:
            console.print(f"[green]Updated {len(linear_result.updated)} issues[/green]")
        if not linear_result.created and not linear_result.updated:
            console.print("[dim]Nothing to sync.[/dim]")
        return

    from devflow.orchestration.sync import DirtyWorktreeError, run_sync
    from devflow.ui.rendering import render_sync_summary

    try:
        sync_result = run_sync(
            dry_run=dry_run,
            keep_artifacts=keep_artifacts,
            prune_orphans=prune_orphans,
        )
    except DirtyWorktreeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from exc

    render_sync_summary(sync_result)


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

    Examples:
      devflow install
      devflow install --check
      devflow install --linear-team ABC
    """
    from devflow.setup.doctor import run_doctor
    from devflow.ui.rendering import render_doctor_report

    if check_only:
        render_header(subtitle="Doctor diagnostic")
        report = run_doctor()
        render_doctor_report(report)
        if not report.passed:
            console.print(
                "\n[dim]Run devflow doctor --fix to attempt auto-remediation.[/dim]"
            )
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
            console.print(
                f"[red]✗ Feature {feature_id!r} not found — not in state.json"
                " — Fix: run devflow status to list features[/red]"
            )
            raise typer.Exit(1)
        render_log_detail(feat)
    else:
        features = list(load_state().features.values())
        render_log_table(features)



@app.command(name="doctor")
def doctor_cmd(
    fix: Annotated[
        bool, typer.Option("--fix", help="Propose and apply fixes for failed checks")
    ] = False,
) -> None:
    """Run diagnostic checks on your devflow installation.

    With --fix, proposes and applies fixes for failed checks.

    Examples:
      devflow doctor
      devflow doctor --fix
    """
    from devflow.setup.doctor import run_doctor
    from devflow.ui.rendering import render_doctor_report

    render_header(subtitle="Doctor diagnostic")

    with contextlib.suppress(Exception):
        _ensure_backend()

    if fix:
        from devflow.setup.doctor import run_doctor_fix

        report = run_doctor_fix()
    else:
        report = run_doctor()

    render_doctor_report(report)
    if not report.passed:
        if not fix:
            console.print(
                "\n[dim]Run devflow doctor --fix to attempt auto-remediation.[/dim]"
            )
        raise typer.Exit(1)


@app.command(name="version", deprecated=True, hidden=True)
def version_cmd() -> None:
    """(Deprecated) Use ``devflow --version``."""
    _deprecation_hint("version", "devflow --version")
    from devflow import __version__

    console.print(f"devflow {__version__}")
