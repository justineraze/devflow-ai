"""Build loop — executes a feature through its phases end-to-end.

Responsible for one thing: running the plan-first confirmation flow,
coordinating phase execution, and creating the PR on success.

Feature lifecycle (create/resume/retry) → lifecycle.py
Phase state machine (run/complete/fail) → phase_exec.py
Model selection                          → model_routing.py
Gate execution                           → integrations/gate/
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.panel import Panel

if TYPE_CHECKING:
    from devflow.ui.rendering import BuildTotals

from devflow.core.artifacts import save_phase_output
from devflow.core.backend import get_backend
from devflow.core.console import console
from devflow.core.metrics import PhaseMetrics
from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseRecord,
    PhaseStatus,
)
from devflow.core.workflow import load_state, mutate_feature
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    run_phase,
    setup_gate_retry,
)

PLANNING_PHASES = frozenset({"architecture", "planning", "plan_review"})


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


def _parse_plan_module(plan_output: str) -> str | None:
    """Extract the module name from the plan's ### Scope section.

    Looks for: ``- Module: <module>``
    Returns the first word of the value, or None if the line is absent.
    """
    import re

    match = re.search(r"^\s*-\s+Module:\s+(\S+)", plan_output, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _parse_plan_title(plan_output: str) -> str | None:
    """Extract the concise title from the plan header.

    Looks for: ``## Plan: <feature-id> — <title>``
    Returns the title part after the em-dash, or None if absent.
    """
    import re

    match = re.search(r"^##\s+Plan:\s+\S+\s+[—–-]\s+(.+)$", plan_output, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


# Map plan Type: values → Conventional Commits prefixes.
_PLAN_TYPE_TO_COMMIT: dict[str, str] = {
    "new-feature": "feat",
    "extension": "feat",
    "bugfix": "fix",
    "refactor": "refactor",
    "docs": "docs",
    "ci": "ci",
    "test": "test",
    "chore": "chore",
    "perf": "perf",
}


def _parse_plan_type(plan_output: str) -> str | None:
    """Extract the Conventional Commits type from the plan's Type: line.

    Looks for: ``- Type: <value>``
    Maps plan-specific values (new-feature, bugfix…) to commit types (feat, fix…).
    Returns None if the line is absent or the value is unknown.
    """
    import re

    match = re.search(r"^\s*-\s+Type:\s+(\S+)", plan_output, re.MULTILINE)
    if not match:
        return None
    return _PLAN_TYPE_TO_COMMIT.get(match.group(1).strip().lower())


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str,
    base: Path | None = None, verbose: bool = False,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via Claude Code or local gate."""
    from devflow.integrations.gate import run_gate_phase
    from devflow.orchestration.runner import execute_phase

    if phase.name == "gate":
        state = load_state(base)
        return run_gate_phase(base, stack=state.stack, feature_id=feature.id)
    return execute_phase(feature, phase, agent_name, verbose=verbose)


def _run_planning_loop(
    feature: Feature,
    totals: BuildTotals,
    stack: str | None,
    base: Path | None = None,
    verbose: bool = False,
) -> tuple[Feature, str, bool]:
    """Run planning phases and return (feature, plan_output, success).

    Stops as soon as a non-planning phase is encountered (resetting it
    back to PENDING so the execution loop picks it up).
    """
    from devflow.orchestration.model_routing import get_phase_agent, resolve_model
    from devflow.ui.rendering import (
        render_phase_failure,
        render_phase_header,
        render_phase_success,
    )

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
        if phase.name not in PLANNING_PHASES:
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    p = tracked.find_phase(phase.name)
                    if p and p.status == PhaseStatus.IN_PROGRESS:
                        p.reset()
            break

        tier = resolve_model(feature, phase)
        model_label = get_backend().model_name(tier)
        render_phase_header(phase_num, total, phase.name, model_label)
        start = time.monotonic()
        success, output, metrics = _execute_phase(feature, phase, agent_name, base, verbose)
        elapsed = time.monotonic() - start

        if not success:
            totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
            fail_phase(feature.id, phase.name, output, base)
            render_phase_failure(phase.name, elapsed, output)
            return feature, "", False

        complete_phase(feature.id, phase.name, output, base)
        render_phase_success(phase.name, elapsed, metrics)
        totals.add(phase.name, metrics, elapsed, model=model_label)

        if phase.name == "planning":
            plan_output = output
            with mutate_feature(feature.id, base) as feat:
                if feat:
                    module = _parse_plan_module(output)
                    if module:
                        feat.metadata.scope = module
                    title = _parse_plan_title(output)
                    if title:
                        feat.metadata.title = title
                    commit_type = _parse_plan_type(output)
                    if commit_type:
                        feat.metadata.commit_type = commit_type

        feature = _refresh_feature(feature.id, base) or feature

    return feature, plan_output, True


def _run_execution_loop(
    feature: Feature,
    totals: BuildTotals,
    initial_untracked: list[str],
    stack: str | None,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
) -> tuple[Feature, bool]:
    """Run implementation, review, gate, and fixing phases.

    Returns (feature, success). Handles auto-commit after implementing/fixing
    and the gate auto-retry loop.
    """
    from devflow.integrations.git import (
        build_commit_message,
        commit_changes,
        get_diff_stat,
        persist_files_summary,
    )
    from devflow.orchestration.model_routing import get_phase_agent, resolve_model
    from devflow.ui.rendering import (
        render_phase_auto_retry,
        render_phase_failure,
        render_phase_header,
        render_phase_success,
    )

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
        render_phase_header(phase_num, total, phase.name, model_label)
        start = time.monotonic()
        success, output, metrics = _execute_phase(feature, phase, agent_name, base, verbose)
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)

            if phase.name == "gate":
                from devflow.ui.gate_panel import render_gate_panel
                render_gate_panel(feature.id, base)
            else:
                render_phase_success(phase.name, elapsed, metrics)
            totals.add(phase.name, metrics, elapsed, model=model_label)

            if phase.name in ("implementing", "fixing"):
                msg = build_commit_message(feature, suffix=phase.name)
                if commit_changes(msg, exclude=initial_untracked):
                    console.print("  [dim]💾 auto-committed changes[/dim]")
                diff = get_diff_stat()
                if diff:
                    console.print("[dim]" + "\n".join(
                        f"  {line}" for line in diff.split("\n")
                    ) + "[/dim]\n")
                persist_files_summary(feature.id, base, base_branch)

            # Review loop: after fixing, re-run reviewing if the workflow
            # includes it and we haven't exhausted the review cycle budget.
            if phase.name == "fixing":
                feature = _refresh_feature(feature.id, base) or feature
                if _should_re_review(feature, base):
                    _setup_re_review(feature.id, base)
                    feature = _refresh_feature(feature.id, base) or feature
                    total = len(feature.phases)
                    continue

            # Review loop: after reviewing, check if reviewer approved.
            # If REQUEST_CHANGES, reset fixing to PENDING and loop.
            if phase.name == "reviewing" and feature.metadata.review_cycles > 0:
                if "APPROVE" in output.upper():
                    # Reviewer approved — proceed to gate normally.
                    pass
                else:
                    # REQUEST_CHANGES — re-do fixing.
                    feature = _refresh_feature(feature.id, base) or feature
                    _setup_re_fix(feature.id, base)
                    feature = _refresh_feature(feature.id, base) or feature
                    total = len(feature.phases)
                    continue
        else:
            totals.add(phase.name, metrics, elapsed, model=model_label, success=False)

            if phase.name == "gate":
                save_phase_output(feature.id, "gate", output, base)
                if setup_gate_retry(feature.id, base):
                    from devflow.ui.gate_panel import render_gate_panel
                    render_gate_panel(feature.id, base)
                    render_phase_auto_retry(phase.name, elapsed, "")
                    feature = _refresh_feature(feature.id, base) or feature
                    continue

            fail_phase(feature.id, phase.name, output, base)
            render_phase_failure(phase.name, elapsed, output)
            return feature, False

        feature = _refresh_feature(feature.id, base) or feature

    return feature, True


MAX_REVIEW_CYCLES = 2


def _should_re_review(feature: Feature, base: Path | None = None) -> bool:
    """Return True if the workflow has a reviewing phase and review budget remains."""
    if feature.metadata.review_cycles >= MAX_REVIEW_CYCLES:
        return False
    return feature.find_phase("reviewing") is not None


def _setup_re_review(feature_id: str, base: Path | None = None) -> None:
    """Reset reviewing to PENDING after fixing, incrementing review_cycles."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        reviewing = feature.find_phase("reviewing")
        if reviewing:
            reviewing.reset()
        feature.metadata.review_cycles += 1


def _setup_re_fix(feature_id: str, base: Path | None = None) -> None:
    """Reset fixing+gate to PENDING after a reviewer REQUEST_CHANGES."""
    from devflow.orchestration.lifecycle import transition_safe

    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        fixing = feature.find_phase("fixing")
        if fixing:
            fixing.reset()
        gate = feature.find_phase("gate")
        if gate:
            gate.reset()
        transition_safe(feature, FeatureStatus.FIXING)


def _finalize_build(
    feature: Feature,
    branch: str,
    totals: BuildTotals,
    initial_untracked: list[str],
    base: Path | None = None,
    base_branch: str = "main",
) -> bool:
    """Push branch, create PR, persist metrics, and render the build summary."""
    from devflow.core.history import append_build_metrics, build_metrics_from
    from devflow.integrations.git import push_and_create_pr
    from devflow.ui.rendering import render_build_summary

    console.print("[dim]Creating PR…[/dim]")

    state = load_state(base)
    final = state.get_feature(feature.id) or feature
    pr_url = (
        push_and_create_pr(final, branch, exclude=initial_untracked, base_branch=base_branch)
        if final else None
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
    if final.metadata.linear_issue_id and state.linear_team_id:
        from devflow.integrations.linear.sync import sync_single_feature

        sync_single_feature(final, state.linear_team_id, base)

    render_build_summary(final, totals, pr_url, branch)
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


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    worktree: bool = False,
    create_pr: bool = True,
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
        4. On failure, hard-reset to the pre-build HEAD

    When ``worktree=True``, the build runs in an isolated git worktree
    under ``.devflow/.worktrees/<feature-id>/``. This allows multiple
    builds to run in parallel without checkout conflicts.
    """
    from devflow.core.history import append_build_metrics, build_metrics_from
    from devflow.integrations.git import (
        branch_name,
        create_branch,
        create_worktree,
        get_head_sha,
        get_untracked_files,
        main_repo_root,
        reset_to_sha,
        switch_branch,
    )
    from devflow.orchestration.phase_exec import reset_planning_phases
    from devflow.ui.rendering import BuildTotals, render_build_banner

    is_resuming = feedback is not None
    # When using worktrees, state always lives in the main repo root.
    if worktree and base is None:
        base = main_repo_root()
    state = load_state(base)
    stack = state.stack
    totals = BuildTotals()
    wt_path: Path | None = None
    branch = ""

    # Save HEAD for potential revert (do mode).
    initial_sha = get_head_sha(short=False) if not create_pr else ""

    # ── Branch / Worktree (build mode only) ──
    if create_pr:
        if worktree:
            branch, wt_path = create_worktree(feature.id)
            initial_untracked = get_untracked_files(cwd=wt_path)
            if is_resuming:
                reset_planning_phases(feature.id, base)
                with mutate_feature(feature.id, base) as tracked:
                    if tracked:
                        tracked.metadata.feedback = feedback
                        feature = tracked
        else:
            initial_untracked = get_untracked_files()
            branch = branch_name(feature.id)
            if is_resuming:
                reset_planning_phases(feature.id, base)
                with mutate_feature(feature.id, base) as tracked:
                    if tracked:
                        tracked.metadata.feedback = feedback
                        feature = tracked
                switch_branch(branch)
            else:
                branch = create_branch(feature.id)
    else:
        initial_untracked = get_untracked_files()

    if create_pr:
        render_build_banner(feature, branch, stack)
    else:
        console.print(f"[bold]do:[/bold] {feature.description}\n")
    if is_resuming:
        console.print(f"[yellow]↻ resumed with feedback:[/yellow] [dim]{feedback}[/dim]\n")

    # ── Planning ──
    feature, plan_output, ok = _run_planning_loop(feature, totals, stack, base, verbose)
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        return False

    # ── Plan confirmation ──
    if plan_output:
        console.print()
        console.print(Panel(
            Markdown(plan_output),
            title="Plan proposé",
            border_style="cyan",
            padding=(1, 2),
        ))
        console.print()

        confirm = console.input("[bold]Lancer l'implémentation ? [Y/n] [/bold]").strip().lower()
        if confirm and confirm not in ("y", "yes", "o", "oui"):
            console.print()
            console.print("[yellow]Build en pause.[/yellow]")
            console.print(f"[dim]Le plan est sauvegardé dans {feature.id}.[/dim]")
            if create_pr:
                console.print()
                console.print("[bold]Reprendre avec :[/bold]")
                console.print(f'  devflow build "ton feedback ici" --resume {feature.id}')
            return False

    # ── Execution ──
    feature, ok = _run_execution_loop(
        feature, totals, initial_untracked, stack, base, verbose, base_branch,
    )
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        # do mode: revert all commits on failure.
        if not create_pr and initial_sha:
            current_sha = get_head_sha(short=False)
            if current_sha != initial_sha:
                console.print(
                    "\n[red bold]Build failed — reverting changes.[/red bold]"
                )
                if reset_to_sha(initial_sha):
                    console.print(f"[dim]Reset to {initial_sha[:7]}.[/dim]\n")
                else:
                    console.print(
                        f"[yellow]Auto-reset failed. "
                        f"Manual reset: git reset --hard {initial_sha[:7]}[/yellow]\n"
                    )
        return False

    # ── Finalize ──
    if create_pr:
        return _finalize_build(feature, branch, totals, initial_untracked, base, base_branch)

    # do mode: print success summary.
    from devflow.ui.rendering import render_build_summary

    current_sha = get_head_sha()
    render_build_summary(feature, totals, pr_url=None, branch="")
    if current_sha != initial_sha[:7]:
        console.print(
            f"[green bold]Done.[/green bold] HEAD is now {current_sha}."
            f"\n[dim]Pour annuler : git reset --hard {initial_sha[:7]}[/dim]\n"
        )
    return True


def execute_do_loop(
    feature: Feature,
    verbose: bool = False,
    base: Path | None = None,
) -> bool:
    """Run a task on the current branch — no branch, no PR.

    Delegates to :func:`execute_build_loop` with ``create_pr=False``.
    On failure, all commits made during the build are reverted.
    """
    return execute_build_loop(feature, base=base, verbose=verbose, create_pr=False)
