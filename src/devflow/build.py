"""Build and fix orchestration — state machine, branch/PR, Claude Code delegation."""

from __future__ import annotations

import re
import subprocess
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


def _run_single_phase(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
    base: Path | None = None,
) -> tuple[bool, str]:
    """Execute a single phase and update state."""
    from devflow.runner import execute_phase, run_gate_phase

    if phase.name == "gate":
        return run_gate_phase(base)
    return execute_phase(feature, phase, agent_name)


def _show_diff_stat() -> None:
    """Show git diff --stat for implemented changes."""
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1"],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
    )
    if diff.stdout.strip():
        console.print("\n[bold]Changements :[/bold]")
        for line in diff.stdout.strip().split("\n"):
            console.print(f"  {line}")


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
    """Resume an existing feature build."""
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

    return feature


def run_phase(
    feature: Feature,
    base: Path | None = None,
) -> PhaseRecord | None:
    """Advance to the next phase, update state machine, persist."""
    state = load_state(base)

    tracked = state.get_feature(feature.id)
    if not tracked:
        return None

    phase = advance_phase(tracked)
    if not phase:
        _transition_safe(tracked, FeatureStatus.GATE)
        _transition_safe(tracked, FeatureStatus.DONE)
        save_state(state, base)
        return None

    target_status = PHASE_TO_STATUS.get(phase.name)
    if target_status and tracked.status != target_status:
        _transition_safe(tracked, target_status)

    save_state(state, base)
    return phase


def _reset_planning_phases(feature_id: str, base: Path | None = None) -> None:
    """Reset planning phases back to pending so they can be re-run."""
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

    # Reset feature status back to pending.
    feature.status = FeatureStatus.PENDING

    save_state(state, base)


def _get_plan_output(feature: Feature) -> str:
    """Extract the planning phase output from a feature."""
    for phase in feature.phases:
        if phase.name == "planning" and phase.output:
            return phase.output
    return ""


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
) -> bool:
    """Run a feature build with plan-first confirmation flow.

    Flow:
    1. Create git branch (or switch to existing one)
    2. Run planning phases — if feedback provided, inject it
    3. Show the plan and ask for confirmation
    4. If refused → pause, user can resume with feedback
    5. If confirmed → run remaining phases, then create PR

    Returns True if the feature completed successfully.
    """
    from devflow.runner import create_branch, create_pull_request

    total = len(feature.phases)
    is_resuming = feedback is not None

    # Header.
    console.print(f"\n[bold cyan]devflow build[/bold cyan] — {feature.description}")
    console.print(
        f"[dim]{feature.id} | workflow: {feature.workflow} | {total} phases[/dim]"
    )

    # Create or switch to feature branch.
    branch = f"feat/{feature.id}"
    if is_resuming:
        # Reset planning to re-run with feedback.
        _reset_planning_phases(feature.id, base)
        state = load_state(base)
        feature = state.get_feature(feature.id) or feature

        # Store feedback in metadata for the planner prompt.
        feature.metadata["feedback"] = feedback
        save_state(state, base)

        # Try to switch to existing branch.
        subprocess.run(
            ["git", "checkout", branch],
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
        )
        console.print(f"[dim]branch: {branch} (resumed)[/dim]")
        console.print(f"[dim]feedback: {feedback}[/dim]\n")
    else:
        branch = create_branch(feature.id)
        console.print(f"[dim]branch: {branch}[/dim]\n")

    # === STEP 1: Run planning phases ===
    plan_output = ""
    phase_num = 0

    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        phase_num += 1
        agent_name = _get_phase_agent(feature, phase.name, base)
        is_planning_phase = phase.name in ("architecture", "planning", "plan_review")

        if not is_planning_phase:
            # Past planning — undo advance, will re-run after confirmation.
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
        start_time = time.monotonic()
        success, output = _run_single_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start_time

        if not success:
            fail_phase(feature.id, phase.name, output, base)
            console.print(f"[red]✗ {phase.name} failed ({_format_duration(elapsed)})[/red]")
            if output:
                for line in output.split("\n")[:3]:
                    console.print(f"  [dim]{line}[/dim]")
            return False

        complete_phase(feature.id, phase.name, output, base)
        console.print(f"[green]✓ {phase.name}[/green] [dim]({_format_duration(elapsed)})[/dim]")

        if phase.name == "planning":
            plan_output = output

        # Refresh feature.
        state = load_state(base)
        tracked = state.get_feature(feature.id)
        if not tracked or tracked.is_terminal:
            break
        feature = tracked

    # === STEP 2: Show plan and ask for confirmation ===
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
            console.print(
                f'  devflow build "ton feedback ici" --resume {feature.id}'
            )
            console.print()
            console.print("[dim]Exemples :[/dim]")
            console.print(
                f'  devflow build "pas de framework detection" --resume {feature.id}'
            )
            console.print(
                f'  devflow build "ajoute aussi le support Go" --resume {feature.id}'
            )
            return False

    # === STEP 3: Run remaining phases ===
    console.print()
    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        phase_num += 1
        agent_name = _get_phase_agent(feature, phase.name, base)

        console.print(f"[dim]Phase {phase_num}/{total}: {phase.name}...[/dim]", end="")
        start_time = time.monotonic()
        success, output = _run_single_phase(feature, phase, agent_name, base)
        elapsed = time.monotonic() - start_time

        if success:
            complete_phase(feature.id, phase.name, output, base)
            console.print(f" [green]✓[/green] [dim]({_format_duration(elapsed)})[/dim]")

            if phase.name == "gate" and output:
                console.print(f"  {output}")
            if phase.name == "implementing":
                _show_diff_stat()
        else:
            fail_phase(feature.id, phase.name, output, base)
            console.print(f" [red]✗[/red] [dim]({_format_duration(elapsed)})[/dim]")
            if output:
                for line in output.split("\n")[:3]:
                    console.print(f"  [dim]{line}[/dim]")
            return False

        # Refresh feature.
        state = load_state(base)
        tracked = state.get_feature(feature.id)
        if not tracked or tracked.is_terminal:
            break
        feature = tracked

    # === STEP 4: Create PR ===
    console.print(f"\n[bold green]✓ Feature complete[/bold green] [{phase_num}/{total}]")

    console.print("[dim]Creating PR...[/dim]")
    state = load_state(base)
    final_feature = state.get_feature(feature.id)
    if final_feature:
        pr_url = create_pull_request(final_feature, branch)
        if pr_url:
            console.print(f"\n[bold green]PR:[/bold green] {pr_url}")
        else:
            console.print("[yellow]PR creation failed — push manually.[/yellow]")

    return True


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
    """Start a bug fix using the quick workflow (no planning phase)."""
    return start_build(description, workflow_name="quick", base=base)


_STACK_AGENT_MAP: dict[str, str] = {
    "python": "developer-python",
    "typescript": "developer-typescript",
    "php": "developer-php",
}


def _get_phase_agent(
    feature: Feature,
    phase_name: str,
    base: Path | None = None,
) -> str:
    """Get the agent name for a phase from the workflow definition.

    When the workflow assigns the generic ``"developer"`` agent and
    a stack has been detected (via ``devflow init``), return the
    language-specific agent instead (e.g. ``"developer-python"``).
    """
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
