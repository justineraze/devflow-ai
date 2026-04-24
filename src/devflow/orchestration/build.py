"""Build loop — executes a feature through its phases end-to-end.

Responsible for one thing: running the plan-first confirmation flow,
coordinating phase execution, and creating the PR on success.

Feature lifecycle (create/resume/retry) → lifecycle.py
Phase state machine (run/complete/fail) → phase_exec.py
Model selection                          → model_routing.py
Gate execution                           → integrations/gate/
Plan output parsing                      → plan_parser.py
Review cycle logic                       → review.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devflow.core.metrics import PhaseResult

from devflow.core.artifacts import save_phase_output
from devflow.core.backend import get_backend
from devflow.core.console import console
from devflow.core.metrics import BuildTotals, PhaseMetrics
from devflow.core.models import (
    Feature,
    PhaseName,
    PhaseRecord,
    PhaseStatus,
    PhaseType,
)
from devflow.core.phases import get_spec
from devflow.core.workflow import load_state, mutate_feature
from devflow.orchestration.events import BuildCallbacks
from devflow.orchestration.model_routing import get_phase_agent, resolve_model
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    run_phase,
    setup_gate_retry,
)
from devflow.orchestration.plan_parser import (
    parse_plan_module,
    parse_plan_title,
    parse_plan_type,
)
from devflow.orchestration.review import (
    setup_re_fix,
    setup_re_review,
    should_re_review,
)


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str,
    base: Path | None = None, verbose: bool = False,
    base_sha: str = "",
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via the backend or local gate."""
    from devflow.integrations.gate import run_gate_phase
    from devflow.orchestration.runner import execute_phase

    if get_spec(phase.name).phase_type == PhaseType.GATE:
        from devflow.core.config import load_config
        return run_gate_phase(
            base, stack=load_config(base).stack,
            feature_id=feature.id, base_sha=base_sha,
        )
    return execute_phase(feature, phase, agent_name, verbose=verbose)


# ── Planning loop ─────────────────────────────────────────────────


def _run_planning_loop(
    feature: Feature,
    totals: BuildTotals,
    stack: str | None,
    callbacks: BuildCallbacks,
    base: Path | None = None,
    verbose: bool = False,
) -> tuple[Feature, str, bool]:
    """Run planning phases and return (feature, plan_output, success).

    Stops as soon as a non-planning phase is encountered (resetting it
    back to PENDING so the execution loop picks it up).
    """
    total = len(feature.phases)
    plan_output = ""
    phase_num = 0

    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        phase_num += 1
        agent_name = get_phase_agent(feature, phase.name, base, stack=stack)

        # Stop before non-planning phases — wait for confirmation.
        if get_spec(phase.name).phase_type != PhaseType.PLANNING:
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    p = tracked.find_phase(phase.name)
                    if p and p.status == PhaseStatus.IN_PROGRESS:
                        p.reset()
            break

        tier = resolve_model(feature, phase)
        model_label = get_backend().model_name(tier)
        callbacks.on_phase_header(phase_num, total, phase.name, model_label)
        start = time.monotonic()
        success, output, metrics = _execute_phase(feature, phase, agent_name, base, verbose)
        elapsed = time.monotonic() - start

        if not success:
            totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
            fail_phase(feature.id, phase.name, output, base)
            callbacks.on_phase_failure(phase.name, elapsed, output)
            return feature, "", False

        complete_phase(feature.id, phase.name, output, base)
        callbacks.on_phase_success(phase.name, elapsed, metrics)
        totals.add(phase.name, metrics, elapsed, model=model_label)

        if phase.name == PhaseName.PLANNING:
            plan_output = output
            with mutate_feature(feature.id, base) as feat:
                if feat:
                    module = parse_plan_module(output)
                    if module:
                        feat.metadata.scope = module
                    title = parse_plan_title(output)
                    if title:
                        feat.metadata.title = title
                    commit_type = parse_plan_type(output)
                    if commit_type:
                        feat.metadata.commit_type = commit_type

        feature = _refresh_feature(feature.id, base) or feature

    return feature, plan_output, True


# ── Post-phase handlers ───────────────────────────────────────────


def _handle_post_phase_commit(
    feature: Feature,
    phase: PhaseRecord,
    pre_phase_sha: str,
    success: bool,
    output: str,
    metrics: PhaseMetrics,
    elapsed: float,
    model_label: str,
    initial_untracked: list[str],
    totals: BuildTotals,
    callbacks: BuildCallbacks,
    base: Path | None,
    base_branch: str,
) -> None:
    """Auto-commit after implementing/fixing and record metrics."""
    from devflow.integrations.git import commit_changes
    from devflow.integrations.git.smart_messages import generate_commit_message
    from devflow.orchestration.phase_artifacts import (
        collect_phase_result,
        persist_files_summary,
    )

    phase_result = collect_phase_result(pre_phase_sha, success, output, metrics)

    # Auto-commit only if agent left uncommitted changes.
    if phase_result.uncommitted_changes:
        msg = generate_commit_message(feature, phase=phase.name)
        if commit_changes(msg, exclude=initial_untracked):
            phase_result = collect_phase_result(pre_phase_sha, success, output, metrics)

    callbacks.on_phase_success(phase.name, elapsed, metrics)
    callbacks.on_phase_commits(phase_result)
    totals.add(
        phase.name, metrics, elapsed, model=model_label,
        commits=len(phase_result.commits),
        files_changed=len(phase_result.files_changed),
        insertions=sum(c.insertions for c in phase_result.commits),
        deletions=sum(c.deletions for c in phase_result.commits),
    )

    _save_phase_commits_artifact(feature.id, phase.name, phase_result, base)
    persist_files_summary(feature.id, base, base_branch)


def _handle_gate_result(
    feature: Feature,
    phase: PhaseRecord,
    output: str,
    metrics: PhaseMetrics,
    elapsed: float,
    model_label: str,
    totals: BuildTotals,
    callbacks: BuildCallbacks,
    base: Path | None,
) -> tuple[Feature, bool]:
    """Handle a gate failure. Returns (feature, should_retry).

    should_retry is True if a gate-retry phase was scheduled; False to abort.
    """
    totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
    save_phase_output(feature.id, "gate", output, base)
    if setup_gate_retry(feature.id, base):
        callbacks.on_gate_panel(feature.id, base)
        callbacks.on_phase_auto_retry(phase.name, elapsed, "")
        feature = _refresh_feature(feature.id, base) or feature
        return feature, True
    return feature, False


# ── Execution loop ────────────────────────────────────────────────


def _run_execution_loop(
    feature: Feature,
    totals: BuildTotals,
    initial_untracked: list[str],
    stack: str | None,
    callbacks: BuildCallbacks,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    base_sha: str = "",
) -> tuple[Feature, bool]:
    """Run implementation, review, gate, and fixing phases.

    Returns (feature, success). Dispatches to handlers for auto-commit,
    gate retry, and review cycles.
    """
    from devflow.integrations.git import get_head_sha

    total = len(feature.phases)

    console.print()
    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        done_count = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
        phase_num = done_count + 1
        agent_name = get_phase_agent(feature, phase.name, base, stack=stack)

        tier = resolve_model(feature, phase)
        model_label = get_backend().model_name(tier)
        callbacks.on_phase_header(phase_num, total, phase.name, model_label)

        # Capture pre-phase SHA for commit tracking.
        spec = get_spec(phase.name)
        is_code_phase = spec.phase_type == PhaseType.CODE
        pre_phase_sha = get_head_sha(short=False) if is_code_phase else ""

        start = time.monotonic()
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, base_sha=base_sha,
        )
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)

            if spec.phase_type == PhaseType.GATE:
                callbacks.on_gate_panel(feature.id, base)
                totals.add(phase.name, metrics, elapsed, model=model_label)
            elif is_code_phase:
                _handle_post_phase_commit(
                    feature, phase, pre_phase_sha, success, output, metrics,
                    elapsed, model_label, initial_untracked, totals, callbacks,
                    base, base_branch,
                )
            else:
                callbacks.on_phase_success(phase.name, elapsed, metrics)
                totals.add(phase.name, metrics, elapsed, model=model_label)

            # Review cycle: after fixing, re-review if budget allows.
            if phase.name == PhaseName.FIXING:
                feature = _refresh_feature(feature.id, base) or feature
                if should_re_review(feature, base):
                    setup_re_review(feature.id, base)
                    feature = _refresh_feature(feature.id, base) or feature
                    total = len(feature.phases)
                    continue

            # Review cycle: after reviewing, check if reviewer approved.
            if (phase.name == PhaseName.REVIEWING
                    and feature.metadata.review_cycles > 0
                    and "APPROVE" not in output.upper()):
                feature = _refresh_feature(feature.id, base) or feature
                setup_re_fix(feature.id, base)
                feature = _refresh_feature(feature.id, base) or feature
                total = len(feature.phases)
                continue
        else:
            # Gate failure with auto-retry.
            if spec.phase_type == PhaseType.GATE:
                feature, should_retry = _handle_gate_result(
                    feature, phase, output, metrics, elapsed,
                    model_label, totals, callbacks, base,
                )
                if should_retry:
                    continue
            else:
                totals.add(phase.name, metrics, elapsed, model=model_label, success=False)

            fail_phase(feature.id, phase.name, output, base)
            callbacks.on_phase_failure(phase.name, elapsed, output)
            return feature, False

        feature = _refresh_feature(feature.id, base) or feature

    return feature, True


def _save_phase_commits_artifact(
    feature_id: str, phase_name: str,
    phase_result: PhaseResult,
    base: Path | None = None,
) -> None:
    """Persist commit summary as a JSON artifact for downstream phases."""
    from devflow.core.artifacts import write_artifact

    data = {
        "commits": [
            {
                "sha": c.sha,
                "message": c.message,
                "files": c.files,
                "insertions": c.insertions,
                "deletions": c.deletions,
            }
            for c in phase_result.commits
        ],
        "total_files": len(phase_result.files_changed),
        "total_insertions": sum(c.insertions for c in phase_result.commits),
        "total_deletions": sum(c.deletions for c in phase_result.commits),
    }
    write_artifact(feature_id, f"{phase_name}.json", json.dumps(data, indent=2), base)


# ── Finalize ──────────────────────────────────────────────────────


def _finalize_build(
    feature: Feature,
    branch: str,
    totals: BuildTotals,
    initial_untracked: list[str],
    callbacks: BuildCallbacks,
    base: Path | None = None,
    base_branch: str = "main",
) -> bool:
    """Push branch, create PR, persist metrics, and render the build summary."""
    from devflow.core.history import append_build_metrics, build_metrics_from
    from devflow.integrations.git import push_and_create_pr

    console.print("[dim]Creating PR…[/dim]")

    state = load_state(base)
    final = state.get_feature(feature.id) or feature
    pr_url = push_and_create_pr(
        final, branch, exclude=initial_untracked, base_branch=base_branch,
    )

    # Persist build metrics for historical tracking.
    record = build_metrics_from(final, totals, success=True)
    append_build_metrics(record, base)

    # Warn if cache hit rate has been consistently low.
    from devflow.core.history import read_history

    recent = read_history(base, limit=3)
    if len(recent) >= 3:
        avg_cache = sum(r.cache_hit_rate for r in recent[:3]) / 3
        if avg_cache < 0.4:
            console.print(
                f"[yellow]⚠ Cache hit rate bas ({int(avg_cache * 100)}%) "
                f"sur les 3 derniers builds. "
                f"Les prompts système ont peut-être changé.[/yellow]"
            )

    # Sync Linear status to "completed" (best-effort).
    from devflow.orchestration.phase_exec import sync_linear_if_configured
    sync_linear_if_configured(final, base)

    callbacks.on_build_summary(final, totals, pr_url, branch, None)
    if pr_url is None:
        console.print("[yellow]PR creation failed — push manually.[/yellow]\n")

    # If this feature is part of an epic, check if the epic is now complete.
    if final.parent_id:
        from devflow.core.epics import check_epic_completion

        if check_epic_completion(final.parent_id, base):
            console.print(
                f"[green bold]Epic {final.parent_id} — all sub-features done![/green bold]\n"
            )

    return True


# ── Main entry points ─────────────────────────────────────────────


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    worktree: bool = False,
    create_pr: bool = True,
    callbacks: BuildCallbacks | None = None,
) -> bool:
    """Run a feature through its phases end-to-end.

    When ``create_pr=True`` (default — ``devflow build``):
        1. Create git branch (or worktree)
        2. Run planning phases — show plan, ask confirmation
        3. Run remaining phases with auto-commit
        4. Create PR on success

    When ``create_pr=False`` (``devflow do``):
        1. Stay on current branch (no branch creation)
        2. Run all phases identically (planning, confirmation, execution)
        3. No PR — on success, print the commit SHAs
        4. On failure, changes stay on branch (user decides)
    """
    from devflow.core.history import append_build_metrics, build_metrics_from
    from devflow.integrations.git import get_head_sha, get_untracked_files, main_repo_root

    cb = callbacks or BuildCallbacks()
    is_resuming = feedback is not None
    if worktree and base is None:
        base = main_repo_root()
    from devflow.core.config import load_config

    config = load_config(base)
    stack = config.stack
    totals = BuildTotals()
    branch = ""

    initial_sha = get_head_sha(short=False)

    # ── Branch / Worktree (build mode only) ──
    if create_pr:
        initial_untracked = _setup_branch(
            feature, base, worktree, is_resuming, feedback,
        )
        branch = _get_branch_name(feature)
    else:
        initial_untracked = get_untracked_files()

    if create_pr:
        cb.on_banner(feature, branch, stack)
    else:
        console.print(f"[bold]do:[/bold] {feature.description}\n")
    if is_resuming:
        console.print(f"[yellow]↻ resumed with feedback:[/yellow] [dim]{feedback}[/dim]\n")

    # ── Planning ──
    feature, plan_output, ok = _run_planning_loop(feature, totals, stack, cb, base, verbose)
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        return False

    # ── Plan confirmation ──
    if plan_output and not cb.confirm_plan(plan_output, feature.id, create_pr):
        return False

    # ── Execution ──
    feature, ok = _run_execution_loop(
        feature, totals, initial_untracked, stack, cb, base, verbose,
        base_branch, base_sha=initial_sha,
    )
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        if not create_pr and initial_sha:
            current_sha = get_head_sha(short=False)
            if current_sha != initial_sha:
                console.print(
                    "\n[yellow]Gate failed. Changes are still on your branch.[/yellow]"
                )
                console.print(
                    f"[dim]Pour annuler : git reset --hard {initial_sha[:7]}[/dim]"
                )
                console.print(
                    f"[dim]Pour réessayer : devflow build --retry {feature.id}[/dim]\n"
                )
        return False

    # ── Finalize ──
    if create_pr:
        return _finalize_build(feature, branch, totals, initial_untracked, cb, base, base_branch)

    # do mode: persist metrics and print success summary.
    feature = _refresh_feature(feature.id, base) or feature
    record = build_metrics_from(feature, totals, success=True)
    append_build_metrics(record, base)

    current_sha = get_head_sha()
    cb.on_build_summary(feature, totals, None, "", None)
    if current_sha != initial_sha[:7]:
        console.print(
            f"[green bold]Done.[/green bold] HEAD is now {current_sha}."
            f"\n[dim]Pour annuler : git reset --hard {initial_sha[:7]}[/dim]\n"
        )
    return True


def _setup_branch(
    feature: Feature,
    base: Path | None,
    worktree: bool,
    is_resuming: bool,
    feedback: str | None,
) -> list[str]:
    """Set up git branch or worktree, return initial untracked files."""
    from devflow.integrations.git import (
        create_branch,
        create_worktree,
        get_untracked_files,
        switch_branch,
    )
    from devflow.orchestration.phase_exec import reset_planning_phases

    if worktree:
        _branch, _wt_path = create_worktree(feature.id)
        initial_untracked = get_untracked_files(cwd=_wt_path)
        if is_resuming:
            reset_planning_phases(feature.id, base)
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    tracked.metadata.feedback = feedback
    else:
        initial_untracked = get_untracked_files()
        from devflow.integrations.git import branch_name
        branch = branch_name(feature.id)
        if is_resuming:
            reset_planning_phases(feature.id, base)
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    tracked.metadata.feedback = feedback
            switch_branch(branch)
        else:
            create_branch(feature.id)

    return initial_untracked


def _get_branch_name(feature: Feature) -> str:
    """Return the branch name for the feature."""
    from devflow.integrations.git import branch_name
    return branch_name(feature.id)


