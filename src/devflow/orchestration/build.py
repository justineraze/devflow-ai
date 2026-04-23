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

    render_build_summary(final, totals, pr_url, branch)
    if pr_url is None:
        console.print("[yellow]PR creation failed — push manually.[/yellow]\n")

    return True


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
) -> bool:
    """Run a feature build with plan-first confirmation flow.

    1. Create git branch
    2. Run planning phases — show plan, ask confirmation
    3. If refused → pause, user can resume with feedback
    4. If confirmed → run remaining phases
    5. Auto-commit after implementing/fixing
    6. Create PR on success
    """
    from devflow.core.history import append_build_metrics, build_metrics_from
    from devflow.integrations.git import (
        branch_name,
        create_branch,
        get_untracked_files,
        switch_branch,
    )
    from devflow.orchestration.phase_exec import reset_planning_phases
    from devflow.ui.rendering import BuildTotals, render_build_banner

    is_resuming = feedback is not None
    state = load_state(base)
    stack = state.stack
    totals = BuildTotals()

    initial_untracked = get_untracked_files()

    # ── Branch ──
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

    render_build_banner(feature, branch, stack)
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
        return False

    # ── PR ──
    return _finalize_build(feature, branch, totals, initial_untracked, base, base_branch)
