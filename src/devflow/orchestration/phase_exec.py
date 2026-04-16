"""Phase state machine — run, complete, fail, and reset phases.

Responsible for one thing: advancing and recording phase status in the
project state. Feature creation lives in lifecycle.py; the build loop
lives in build.py.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseStatus
from devflow.core.phases import UnknownPhase, get_spec
from devflow.core.workflow import advance_phase, mutate_feature
from devflow.orchestration.lifecycle import _transition_safe


def _walk_to_done(feature: Feature) -> None:
    """Transition the feature to DONE after all phases complete.

    Every non-terminal state has DONE as a valid transition (enforced in
    VALID_TRANSITIONS), so a single targeted call is sufficient.
    """
    _transition_safe(feature, FeatureStatus.DONE)


def run_phase(feature: Feature, base: Path | None = None) -> PhaseRecord | None:
    """Advance to the next phase, update state machine, persist."""
    with mutate_feature(feature.id, base) as tracked:
        if not tracked:
            return None

        phase = advance_phase(tracked)
        if not phase:
            _walk_to_done(tracked)
            return None

        try:
            target_status = get_spec(phase.name).feature_status
        except UnknownPhase:
            target_status = None
        if target_status and tracked.status != target_status:
            _transition_safe(tracked, target_status)

        return phase


def complete_phase(
    feature_id: str, phase_name: str, output: str = "", base: Path | None = None,
) -> None:
    """Mark a phase as completed and persist state.

    The output is saved to disk as an artifact, then cleared from the
    PhaseRecord before persisting state.json — avoiding duplication of
    potentially large strings in the state file.
    """
    from devflow.core.artifacts import save_phase_output

    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        phase = feature.find_phase(phase_name)
        if phase and phase.status == PhaseStatus.IN_PROGRESS:
            phase.complete(output)
            if output:
                save_phase_output(feature_id, phase_name, output, base)
                phase.output = ""


def fail_phase(
    feature_id: str, phase_name: str, error: str = "", base: Path | None = None,
) -> None:
    """Mark a phase as failed and persist state."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        phase = feature.find_phase(phase_name)
        if phase and phase.status == PhaseStatus.IN_PROGRESS:
            phase.fail(error)
        _transition_safe(feature, FeatureStatus.FAILED)


def reset_planning_phases(feature_id: str, base: Path | None = None) -> None:
    """Reset planning phases back to pending for re-planning with feedback."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        for phase in feature.phases:
            if phase.name in ("architecture", "planning", "plan_review"):
                phase.reset()
        feature.status = FeatureStatus.PENDING
