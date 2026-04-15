"""Build loop — executes a feature through its phases end-to-end.

Responsible for one thing: running the plan-first confirmation flow,
coordinating phase execution, and creating the PR on success.

Feature lifecycle (create/resume/retry) → lifecycle.py
Phase state machine (run/complete/fail) → phase_exec.py
Model selection                          → model_routing.py
Gate execution                           → integrations/gate.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rich.markdown import Markdown
from rich.panel import Panel

from devflow.core.artifacts import read_artifact, save_phase_output, write_artifact
from devflow.core.metrics import PhaseMetrics
from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.core.workflow import load_state, load_workflow, save_state
from devflow.orchestration.lifecycle import _transition_safe
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    reset_planning_phases,
    run_phase,
)
from devflow.ui.console import console


def _get_phase_agent(
    feature: Feature,
    phase_name: str,
    base: Path | None = None,
) -> str:
    """Return the agent name for a phase, with stack-aware override."""
    from devflow.orchestration.model_routing import agent_for_stack

    agent = "developer"
    try:
        wf = load_workflow(feature.workflow)
        for phase_def in wf.phases:
            if phase_def.name == phase_name:
                agent = phase_def.agent
                break
    except FileNotFoundError:
        pass

    if agent == "developer":
        state = load_state(base)
        specialized = agent_for_stack(state.stack)
        if specialized:
            agent = specialized

    return agent


# File/path patterns that must never trigger a model downgrade.
CRITICAL_PATH_PATTERNS: tuple[str, ...] = (
    "auth", "secret", "token", "crypto", "payment", "billing", "password",
)


def _persist_files_summary(feature_id: str, base: Path | None = None) -> None:
    """Write files.json capturing the branch-diff summary for downstream phases."""
    from devflow.integrations.git import get_branch_diff_summary

    summary = get_branch_diff_summary()
    paths = summary.get("paths") or []
    critical = [
        p for p in paths
        if any(pat in p.lower() for pat in CRITICAL_PATH_PATTERNS)
    ]
    summary["critical_paths"] = critical
    write_artifact(feature_id, "files.json", json.dumps(summary, indent=2), base)


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


MAX_GATE_AUTO_RETRIES = 1


def _setup_gate_retry(feature_id: str, base: Path | None = None) -> bool:
    """Reset gate+fixing to PENDING for one automatic retry loop.

    Returns True when a retry was scheduled, False when the budget is
    exhausted (caller should fall back to the normal failure path).
    """
    state = load_state(base)
    feature = state.get_feature(feature_id)
    if not feature:
        return False

    attempts = feature.metadata.gate_retry
    if attempts >= MAX_GATE_AUTO_RETRIES:
        return False

    gate_phase = next((p for p in feature.phases if p.name == "gate"), None)
    if not gate_phase:
        return False

    fixing_phase = next((p for p in feature.phases if p.name == "fixing"), None)
    if fixing_phase is None:
        fixing_phase = PhaseRecord(name="fixing", status=PhaseStatus.PENDING)
        gate_idx = feature.phases.index(gate_phase)
        feature.phases.insert(gate_idx, fixing_phase)
    else:
        fixing_phase.reset()

    gate_phase.reset()
    feature.metadata.gate_retry = attempts + 1
    _transition_safe(feature, FeatureStatus.FIXING)
    save_state(state, base)
    return True


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str, base: Path | None = None,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via Claude Code or local gate."""
    from devflow.integrations.gate import run_gate_phase
    from devflow.orchestration.runner import execute_phase

    if phase.name == "gate":
        state = load_state(base)
        return run_gate_phase(base, stack=state.stack, feature_id=feature.id)
    return execute_phase(feature, phase, agent_name)


def _render_gate_panel(feature_id: str, base: Path | None = None) -> None:
    """Load gate.json from artifacts and render it as a Rich panel."""
    from devflow.integrations.gate import CheckResult, GateReport, render_gate_report

    raw = read_artifact(feature_id, "gate.json", base)
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    report = GateReport(checks=[
        CheckResult(
            name=c.get("name", "?"),
            passed=bool(c.get("passed", False)),
            skipped=bool(c.get("skipped", False)),
            message=c.get("message", ""),
            details=c.get("details", ""),
        )
        for c in data.get("checks", [])
    ])
    render_gate_report(report)


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
) -> bool:
    """Run a feature build with plan-first confirmation flow.

    1. Create git branch
    2. Run planning phases — show plan, ask confirmation
    3. If refused → pause, user can resume with feedback
    4. If confirmed → run remaining phases
    5. Auto-commit after implementing/fixing
    6. Create PR on success
    """
    from devflow.integrations.git import (
        branch_name,
        build_commit_message,
        commit_changes,
        create_branch,
        get_diff_stat,
        push_and_create_pr,
        switch_branch,
    )
    from devflow.orchestration.model_routing import resolve_model
    from devflow.ui.rendering import (
        BuildTotals,
        render_build_banner,
        render_build_summary,
        render_phase_auto_retry,
        render_phase_failure,
        render_phase_header,
        render_phase_success,
    )

    total = len(feature.phases)
    is_resuming = feedback is not None
    state = load_state(base)
    stack = state.stack
    totals = BuildTotals()

    # ── Branch ──
    branch = branch_name(feature.id)
    if is_resuming:
        reset_planning_phases(feature.id, base)
        state = load_state(base)
        feature = state.get_feature(feature.id) or feature
        feature.metadata.feedback = feedback
        save_state(state, base)
        switch_branch(branch)
    else:
        branch = create_branch(feature.id)

    render_build_banner(feature, branch, stack)
    if is_resuming:
        console.print(f"[yellow]↻ resumed with feedback:[/yellow] [dim]{feedback}[/dim]\n")

    # ── STEP 1: Planning phases ──
    plan_output = ""
    phase_num = 0

    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        phase_num += 1
        agent_name = _get_phase_agent(feature, phase.name, base)

        # Stop before non-planning phases — wait for confirmation.
        if phase.name not in ("architecture", "planning", "plan_review"):
            state = load_state(base)
            tracked = state.get_feature(feature.id)
            if tracked:
                for p in tracked.phases:
                    if p.name == phase.name and p.status == PhaseStatus.IN_PROGRESS:
                        p.reset()
                        break
                save_state(state, base)
            break

        render_phase_header(phase_num, total, phase.name, resolve_model(feature, phase))
        start = time.monotonic()
        success, output, metrics = _execute_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start

        if not success:
            fail_phase(feature.id, phase.name, output, base)
            render_phase_failure(phase.name, elapsed, output)
            return False

        complete_phase(feature.id, phase.name, output, base)
        render_phase_success(phase.name, elapsed, metrics)
        totals.add(phase.name, metrics, elapsed)

        if phase.name == "planning":
            plan_output = output
            module = _parse_plan_module(output)
            if module:
                state = load_state(base)
                feat = state.get_feature(feature.id)
                if feat:
                    feat.metadata.scope = module
                    save_state(state, base)

        feature = _refresh_feature(feature.id, base) or feature

    # ── STEP 2: Show plan + confirm ──
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

    # ── STEP 3: Run remaining phases ──
    console.print()
    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        done_count = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
        phase_num = done_count + 1
        agent_name = _get_phase_agent(feature, phase.name, base)

        render_phase_header(phase_num, total, phase.name, resolve_model(feature, phase))
        start = time.monotonic()
        success, output, metrics = _execute_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)

            if phase.name == "gate":
                _render_gate_panel(feature.id, base)
            else:
                render_phase_success(phase.name, elapsed, metrics)
            totals.add(phase.name, metrics, elapsed)

            if phase.name in ("implementing", "fixing"):
                msg = build_commit_message(feature, suffix=phase.name)
                if commit_changes(msg):
                    console.print("  [dim]💾 auto-committed changes[/dim]")
                diff = get_diff_stat()
                if diff:
                    console.print("[dim]" + "\n".join(
                        f"  {line}" for line in diff.split("\n")
                    ) + "[/dim]\n")
                _persist_files_summary(feature.id, base)
        else:
            if phase.name == "gate":
                save_phase_output(feature.id, "gate", output, base)
                if _setup_gate_retry(feature.id, base):
                    _render_gate_panel(feature.id, base)
                    render_phase_auto_retry(phase.name, elapsed, "")
                    feature = _refresh_feature(feature.id, base) or feature
                    continue

            fail_phase(feature.id, phase.name, output, base)
            render_phase_failure(phase.name, elapsed, output)
            return False

        feature = _refresh_feature(feature.id, base) or feature

    # ── STEP 4: Create PR ──
    console.print("[dim]Creating PR…[/dim]")

    state = load_state(base)
    final = state.get_feature(feature.id) or feature
    pr_url = push_and_create_pr(final, branch) if final else None

    render_build_summary(final, totals, pr_url, branch)
    if pr_url is None:
        console.print("[yellow]PR creation failed — push manually.[/yellow]\n")

    return True
