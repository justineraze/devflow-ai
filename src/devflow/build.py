"""Build and fix orchestration — state machine, phases, confirmation flow."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from devflow.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.workflow import (
    advance_phase,
    create_feature,
    load_state,
    load_workflow,
    save_state,
)

console = Console()

# Map workflow phase names to feature status transitions.
PHASE_TO_STATUS: dict[str, FeatureStatus] = {
    "architecture": FeatureStatus.PLANNING,
    "planning": FeatureStatus.PLANNING,
    "plan_review": FeatureStatus.PLAN_REVIEW,
    "implementing": FeatureStatus.IMPLEMENTING,
    "reviewing": FeatureStatus.REVIEWING,
    "fixing": FeatureStatus.FIXING,
    "gate": FeatureStatus.GATE,
}

# Stack → specialized developer agent.
_STACK_AGENT_MAP: dict[str, str] = {
    "python": "developer-python",
    "typescript": "developer-typescript",
    "php": "developer-php",
}


def _generate_feature_id(description: str) -> str:
    """Generate a short feature ID from description."""
    words = re.sub(r"[^a-zA-Z0-9\s]", "", description.lower()).split()
    slug = "-".join(words[:3])
    timestamp = datetime.now(UTC).strftime("%m%d")
    return f"feat-{slug}-{timestamp}" if slug else f"feat-{timestamp}"


def _transition_safe(feature: Feature, target: FeatureStatus) -> bool:
    """Attempt a state transition, returning True if successful."""
    try:
        feature.transition_to(target)
        return True
    except Exception:
        return False


def _format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m{secs:02d}s"


def _get_phase_agent(
    feature: Feature,
    phase_name: str,
    base: Path | None = None,
) -> str:
    """Get the agent name for a phase, with stack-aware override."""
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
        if state.stack and state.stack in _STACK_AGENT_MAP:
            agent = _STACK_AGENT_MAP[state.stack]

    return agent


# ── Feature lifecycle ──────────────────────────────────────────────────


def start_build(
    description: str,
    workflow_name: str = "standard",
    base: Path | None = None,
) -> Feature:
    """Start a new feature build."""
    state = load_state(base)
    feature_id = _generate_feature_id(description)

    counter = 1
    original_id = feature_id
    while feature_id in state.features:
        counter += 1
        feature_id = f"{original_id}-{counter}"

    feature = create_feature(state, feature_id, description, workflow_name)
    save_state(state, base)
    return feature


def resume_build(
    feature_id: str,
    base: Path | None = None,
) -> Feature | None:
    """Resume an existing feature build.

    If the feature is failed, resets the failed phase to pending
    so it can be retried.
    """
    state = load_state(base)
    feature = state.get_feature(feature_id)

    if not feature:
        console.print(f"[red]Feature {feature_id!r} not found.[/red]")
        return None
    if feature.is_terminal:
        console.print(
            f"[yellow]Feature {feature_id!r} is already {feature.status.value}.[/yellow]"
        )
        return None

    # Recover from failed: reset the failed phase to pending.
    if feature.status == FeatureStatus.FAILED:
        _recover_failed_feature(feature)
        save_state(state, base)
        console.print(f"[cyan]Recovering {feature_id} from failed state.[/cyan]")

    return feature


def _recover_failed_feature(feature: Feature) -> None:
    """Reset a failed feature so it can be retried.

    Finds the last failed phase, resets it to pending, and sets
    the feature status to the appropriate state for that phase.
    """
    for phase in reversed(feature.phases):
        if phase.status == PhaseStatus.FAILED:
            phase.status = PhaseStatus.PENDING
            phase.started_at = None
            phase.completed_at = None
            phase.error = ""

            # Reset to PENDING, then walk forward through done phases.
            feature.status = FeatureStatus.PENDING
            # Walk forward to the state just before the failed phase.
            for p in feature.phases:
                if p.name == phase.name:
                    break
                if p.status == PhaseStatus.DONE:
                    t = PHASE_TO_STATUS.get(p.name)
                    if t:
                        _transition_safe(feature, t)
            return


def retry_build(
    feature_id: str,
    base: Path | None = None,
) -> Feature | None:
    """Retry a failed feature by resetting the failed phase.

    Unlike resume_build, this is strictly for FAILED features
    and skips any feedback/re-planning flow.
    """
    state = load_state(base)
    feature = state.get_feature(feature_id)

    if not feature:
        console.print(f"[red]Feature {feature_id!r} not found.[/red]")
        return None

    if feature.status != FeatureStatus.FAILED:
        console.print(
            f"[yellow]Feature {feature_id!r} is {feature.status.value}, not failed.[/yellow]"
        )
        return None

    _recover_failed_feature(feature)
    save_state(state, base)
    console.print(f"[cyan]Retrying {feature_id} — reset failed phase to pending.[/cyan]")
    return feature


def start_fix(description: str, base: Path | None = None) -> Feature:
    """Start a bug fix using the quick workflow (no planning phase)."""
    return start_build(description, workflow_name="quick", base=base)


# ── Phase management ───────────────────────────────────────────────────


def _walk_to_done(feature: Feature) -> None:
    """Walk the state machine from the current state through to DONE.

    Tries each intermediate state that can reach DONE, silently
    skipping invalid transitions.
    """
    path = [
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.GATE,
        FeatureStatus.DONE,
    ]
    for target in path:
        if feature.status == target:
            continue
        _transition_safe(feature, target)


def run_phase(feature: Feature, base: Path | None = None) -> PhaseRecord | None:
    """Advance to the next phase, update state machine, persist."""
    state = load_state(base)
    tracked = state.get_feature(feature.id)
    if not tracked:
        return None

    phase = advance_phase(tracked)
    if not phase:
        # All phases done — walk the state machine forward to DONE.
        _walk_to_done(tracked)
        save_state(state, base)
        return None

    target_status = PHASE_TO_STATUS.get(phase.name)
    if target_status and tracked.status != target_status:
        _transition_safe(tracked, target_status)

    save_state(state, base)
    return phase


def complete_phase(
    feature_id: str, phase_name: str, output: str = "", base: Path | None = None,
) -> None:
    """Mark a phase as completed and persist state."""
    state = load_state(base)
    feature = state.get_feature(feature_id)
    if not feature:
        return
    for phase in feature.phases:
        if phase.name == phase_name and phase.status == PhaseStatus.IN_PROGRESS:
            phase.complete(output)
            break
    save_state(state, base)


def fail_phase(
    feature_id: str, phase_name: str, error: str = "", base: Path | None = None,
) -> None:
    """Mark a phase as failed and persist state."""
    state = load_state(base)
    feature = state.get_feature(feature_id)
    if not feature:
        return
    for phase in feature.phases:
        if phase.name == phase_name and phase.status == PhaseStatus.IN_PROGRESS:
            phase.fail(error)
            break
    _transition_safe(feature, FeatureStatus.FAILED)
    save_state(state, base)


def _reset_planning_phases(feature_id: str, base: Path | None = None) -> None:
    """Reset planning phases back to pending for re-planning with feedback."""
    state = load_state(base)
    feature = state.get_feature(feature_id)
    if not feature:
        return
    for phase in feature.phases:
        if phase.name in ("architecture", "planning", "plan_review"):
            phase.status = PhaseStatus.PENDING
            phase.started_at = None
            phase.completed_at = None
            phase.output = ""
    feature.status = FeatureStatus.PENDING
    save_state(state, base)


# ── Execution helpers ──────────────────────────────────────────────────


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str, base: Path | None = None,
) -> tuple[bool, str]:
    """Execute a single phase via Claude Code or local gate."""
    from devflow.runner import execute_phase, run_gate_phase

    if phase.name == "gate":
        return run_gate_phase(base)
    return execute_phase(feature, phase, agent_name)


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


# ── Main build loop ───────────────────────────────────────────────────


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
    from devflow.git import (
        build_commit_message,
        commit_changes,
        create_branch,
        get_diff_stat,
        push_and_create_pr,
        switch_branch,
    )

    total = len(feature.phases)
    is_resuming = feedback is not None

    # ── Header ──
    console.print(f"\n[bold cyan]devflow build[/bold cyan] — {feature.description}")
    console.print(f"[dim]{feature.id} | workflow: {feature.workflow} | {total} phases[/dim]")

    # ── Branch ──
    branch = f"feat/{feature.id}"
    if is_resuming:
        _reset_planning_phases(feature.id, base)
        state = load_state(base)
        feature = state.get_feature(feature.id) or feature
        feature.metadata["feedback"] = feedback
        save_state(state, base)
        switch_branch(branch)
        console.print(f"[dim]branch: {branch} (resumed)[/dim]")
        console.print(f"[dim]feedback: {feedback}[/dim]\n")
    else:
        branch = create_branch(feature.id)
        console.print(f"[dim]branch: {branch}[/dim]\n")

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
                        p.status = PhaseStatus.PENDING
                        p.started_at = None
                        break
                save_state(state, base)
            break

        console.print(f"[dim]Phase {phase_num}/{total}: {phase.name}...[/dim]")
        start = time.monotonic()
        success, output = _execute_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start

        if not success:
            fail_phase(feature.id, phase.name, output, base)
            console.print(f"[red]✗ {phase.name} failed ({_format_duration(elapsed)})[/red]")
            if output:
                for line in output.split("\n")[:5]:
                    console.print(f"  [dim]{line}[/dim]")
            return False

        complete_phase(feature.id, phase.name, output, base)
        console.print(f"[green]✓ {phase.name}[/green] [dim]({_format_duration(elapsed)})[/dim]")

        if phase.name == "planning":
            plan_output = output

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

        console.print(f"[dim]Phase {phase_num}/{total}: {phase.name}...[/dim]", end="")
        start = time.monotonic()
        success, output = _execute_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)
            console.print(f" [green]✓[/green] [dim]({_format_duration(elapsed)})[/dim]")

            # Auto-commit after code-changing phases.
            if phase.name in ("implementing", "fixing"):
                msg = build_commit_message(feature, suffix=phase.name)
                if commit_changes(msg):
                    console.print("  [dim]Auto-committed changes[/dim]")
                diff = get_diff_stat()
                if diff:
                    console.print("\n[bold]Changements :[/bold]")
                    for line in diff.split("\n"):
                        console.print(f"  {line}")

            # Show gate results.
            if phase.name == "gate" and output:
                for line in output.split("\n"):
                    console.print(f"  {line}")
        else:
            fail_phase(feature.id, phase.name, output, base)
            console.print(f" [red]✗[/red] [dim]({_format_duration(elapsed)})[/dim]")
            if output:
                for line in output.split("\n")[:5]:
                    console.print(f"  [dim]{line}[/dim]")
            return False

        feature = _refresh_feature(feature.id, base) or feature

    # ── STEP 4: Create PR ──
    console.print(f"\n[bold green]✓ Feature complete[/bold green] [{total}/{total}]")
    console.print("[dim]Creating PR...[/dim]")

    state = load_state(base)
    final = state.get_feature(feature.id)
    if final:
        pr_url = push_and_create_pr(final, branch)
        if pr_url:
            console.print(f"\n[bold green]PR:[/bold green] {pr_url}")
        else:
            console.print("[yellow]PR creation failed — push manually.[/yellow]")

    return True
