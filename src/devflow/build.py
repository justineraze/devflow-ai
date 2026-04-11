"""Build and fix orchestration — state machine updates and Claude Code delegation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from devflow.display import render_feature_detail, render_header, render_phase_progress
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


def _generate_feature_id(description: str) -> str:
    """Generate a short feature ID from description.

    Takes the first 3 significant words and slugifies them.
    Example: 'Add user authentication' -> 'feat-add-user-auth'
    """
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


def start_build(
    description: str,
    workflow_name: str = "standard",
    base: Path | None = None,
) -> Feature:
    """Start a new feature build.

    Creates the feature in state.json and prepares for the first phase.
    Returns the created Feature.
    """
    state = load_state(base)
    feature_id = _generate_feature_id(description)

    # Avoid ID collisions.
    counter = 1
    original_id = feature_id
    while feature_id in state.features:
        counter += 1
        feature_id = f"{original_id}-{counter}"

    feature = create_feature(state, feature_id, description, workflow_name)
    save_state(state, base)

    render_header(subtitle=f"Building: {description}")
    console.print(f"[green]Created feature:[/green] {feature_id}")
    console.print(f"[dim]Workflow: {workflow_name} ({len(feature.phases)} phases)[/dim]")

    return feature


def resume_build(
    feature_id: str,
    base: Path | None = None,
) -> Feature | None:
    """Resume an existing feature build.

    Returns the Feature, or None if not found.
    """
    state = load_state(base)
    feature = state.get_feature(feature_id)

    if not feature:
        console.print(f"[red]Feature {feature_id!r} not found.[/red]")
        return None

    if feature.is_terminal:
        console.print(
            f"[yellow]Feature {feature_id!r} is already"
            f" {feature.status.value}.[/yellow]"
        )
        return None

    render_header(subtitle=f"Resuming: {feature.description}")
    render_feature_detail(feature)

    return feature


def run_phase(
    feature: Feature,
    base: Path | None = None,
) -> PhaseRecord | None:
    """Advance to the next phase and prepare for execution.

    Updates the state machine, persists state, and returns the phase
    to execute. Returns None if all phases are complete.
    """
    state = load_state(base)

    # Sync the feature reference from loaded state.
    tracked = state.get_feature(feature.id)
    if not tracked:
        console.print(f"[red]Feature {feature.id!r} lost from state.[/red]")
        return None

    phase = advance_phase(tracked)
    if not phase:
        # All phases done — transition to DONE.
        _transition_safe(tracked, FeatureStatus.GATE)
        _transition_safe(tracked, FeatureStatus.DONE)
        save_state(state, base)
        console.print(f"[green]All phases complete for {tracked.id}.[/green]")
        render_phase_progress(tracked)
        return None

    # Transition the feature status to match the phase.
    target_status = PHASE_TO_STATUS.get(phase.name)
    if target_status and tracked.status != target_status:
        _transition_safe(tracked, target_status)

    save_state(state, base)

    console.print(f"\n[bold]Phase:[/bold] {phase.name}")
    console.print(f"[dim]Agent: {_get_phase_agent(tracked, phase.name)}[/dim]")
    render_phase_progress(tracked)

    return phase


def execute_build_loop(
    feature: Feature,
    dry_run: bool = False,
    base: Path | None = None,
) -> bool:
    """Run all remaining phases of a feature through Claude Code.

    This is the main orchestration loop:
    1. Advance to the next phase
    2. Execute it (Claude Code or gate)
    3. Mark done/failed
    4. Repeat until all phases complete or a phase fails

    Returns True if the feature completed successfully.
    """
    from devflow.runner import execute_phase, run_gate_phase

    while True:
        phase = run_phase(feature, base)
        if not phase:
            return True  # All phases done.

        agent_name = _get_phase_agent(feature, phase.name)

        # Gate phase runs locally, not through Claude Code.
        if phase.name == "gate":
            success, output = run_gate_phase(base)
        else:
            # Load timeout from workflow definition.
            timeout = _get_phase_timeout(feature, phase.name)
            success, output = execute_phase(
                feature, phase, agent_name,
                timeout=timeout, dry_run=dry_run,
            )

        if success:
            complete_phase(feature.id, phase.name, output, base)
            console.print(f"[green]✓ Phase {phase.name!r} complete[/green]")
        else:
            fail_phase(feature.id, phase.name, output, base)
            console.print(f"[red]✗ Phase {phase.name!r} failed[/red]")
            if output:
                console.print(f"[dim]{output[:500]}[/dim]")
            return False

        # Refresh feature from state (phases are updated on disk).
        state = load_state(base)
        tracked = state.get_feature(feature.id)
        if not tracked or tracked.is_terminal:
            return tracked.status == FeatureStatus.DONE if tracked else False
        feature = tracked

    return False


def complete_phase(
    feature_id: str,
    phase_name: str,
    output: str = "",
    base: Path | None = None,
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
    feature_id: str,
    phase_name: str,
    error: str = "",
    base: Path | None = None,
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


def start_fix(
    description: str,
    base: Path | None = None,
) -> Feature:
    """Start a bug fix using the quick workflow (no planning phase).

    Returns the created Feature.
    """
    return start_build(description, workflow_name="quick", base=base)


def _get_phase_agent(feature: Feature, phase_name: str) -> str:
    """Get the agent name for a phase from the workflow definition."""
    try:
        wf = load_workflow(feature.workflow)
        for phase_def in wf.phases:
            if phase_def.name == phase_name:
                return phase_def.agent
    except FileNotFoundError:
        pass
    return "developer"


def _get_phase_timeout(feature: Feature, phase_name: str) -> int:
    """Get the timeout for a phase from the workflow definition."""
    try:
        wf = load_workflow(feature.workflow)
        for phase_def in wf.phases:
            if phase_def.name == phase_name:
                return phase_def.timeout
    except FileNotFoundError:
        pass
    return 600
