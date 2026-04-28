"""Planning loop — runs planning phases and extracts plan metadata.

Extracted from build.py to keep the orchestrator focused on wiring.
"""

from __future__ import annotations

import time
from pathlib import Path

from devflow.core.backend import get_backend
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
from devflow.integrations.gate import run_gate_phase
from devflow.orchestration import runner
from devflow.orchestration.events import (
    BuildCallbacks,
    PhaseToolListenerFactory,
    _silent_phase_listener,
)
from devflow.orchestration.model_routing import get_phase_agent, resolve_model
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    run_phase,
)
from devflow.orchestration.plan_parser import (
    parse_plan_module,
    parse_plan_title,
    parse_plan_type,
)


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str,
    base: Path | None = None, verbose: bool = False,
    base_sha: str = "",
    stack: str | None = None,
    phase_tool_listener: PhaseToolListenerFactory = _silent_phase_listener,
    cwd: Path | None = None,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via the backend or local gate."""
    if get_spec(phase.name).phase_type == PhaseType.GATE:
        return run_gate_phase(
            cwd or base, stack=stack,
            feature_id=feature.id, base_sha=base_sha,
        )
    return runner.execute_phase(
        feature, phase, agent_name, verbose=verbose,
        phase_tool_listener=phase_tool_listener,
        cwd=cwd,
    )


def _persist_plan_metadata(feature_id: str, plan_output: str, base: Path | None) -> None:
    """Extract and save plan-derived metadata (scope, title, commit_type)."""
    module = parse_plan_module(plan_output)
    title = parse_plan_title(plan_output)
    commit_type = parse_plan_type(plan_output)
    if not (module or title or commit_type):
        return
    with mutate_feature(feature_id, base) as feat:
        if not feat:
            return
        if module:
            feat.metadata.scope = module
        if title:
            feat.metadata.title = title
        if commit_type:
            feat.metadata.commit_type = commit_type


def run_planning_loop(
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
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, stack=stack,
            phase_tool_listener=callbacks.phase_tool_listener,
            cwd=None,
        )
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
            _persist_plan_metadata(feature.id, output, base)

        feature = _refresh_feature(feature.id, base) or feature

    return feature, plan_output, True
