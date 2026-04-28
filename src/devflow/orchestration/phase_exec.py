"""Phase state machine — run, complete, fail, and reset phases.

Responsible for one thing: advancing and recording phase status in the
project state. Feature creation lives in lifecycle.py; the build loop
lives in build.py.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from devflow.core.artifacts import save_phase_output
from devflow.core.backend import ModelTier
from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseName,
    PhaseRecord,
    PhaseStatus,
    PhaseType,
)
from devflow.core.phases import UnknownPhase, get_spec
from devflow.core.registry import get_tracker
from devflow.core.workflow import advance_phase, mutate_feature
from devflow.orchestration.lifecycle import transition_safe

_log = structlog.get_logger(__name__)


def sync_linear_if_configured(
    feature: Feature, base: Path | None = None,
) -> None:
    """Sync tracker issue status for *feature* (best-effort, no-op if unconfigured)."""
    if not feature.metadata.linear_issue_id:
        return
    tracker = get_tracker()
    if tracker is None:
        return
    try:
        tracker.update_status(
            issue_id=feature.metadata.linear_issue_id,
            status=feature.status,
        )
    except Exception as exc:
        _log.warning("Tracker sync failed for %s: %s", feature.id, exc)


def _walk_to_done(feature: Feature) -> None:
    """Transition the feature to DONE after all phases complete.

    Every non-terminal state has DONE as a valid transition (enforced in
    VALID_TRANSITIONS), so a single targeted call is sufficient.
    """
    transition_safe(feature, FeatureStatus.DONE)


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
            transition_safe(tracked, target_status)

        return phase


def complete_phase(
    feature_id: str, phase_name: str, output: str = "", base: Path | None = None,
) -> None:
    """Mark a phase as completed and persist state.

    The output is saved to disk as an artifact, then cleared from the
    PhaseRecord before persisting state.json — avoiding duplication of
    potentially large strings in the state file.
    """
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
        transition_safe(feature, FeatureStatus.FAILED)
        sync_linear_if_configured(feature, base)


def reset_planning_phases(feature_id: str, base: Path | None = None) -> None:
    """Reset planning phases back to pending for re-planning with feedback."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        for phase in feature.phases:
            if get_spec(phase.name).phase_type == PhaseType.PLANNING:
                phase.reset()
        feature.status = FeatureStatus.PENDING


MAX_GATE_AUTO_RETRIES = 3

# Tier escalation per retry attempt (1-indexed).
# retry 1 → no escalation (None lets the selector decide),
# retry 2 → STANDARD, retry 3 → THINKING. Stays in core ModelTier
# space so we don't leak Claude-specific aliases (haiku/sonnet/opus) up
# into orchestration; each backend maps ModelTier to its own model id.
_RETRY_TIER_ESCALATION: dict[int, ModelTier] = {
    2: ModelTier.STANDARD,
    3: ModelTier.THINKING,
}


def setup_gate_retry(feature_id: str, base: Path | None = None) -> bool:
    """Reset gate+fixing to PENDING for an automatic retry loop.

    Escalates the model tier on retries 2 and 3 to increase the chance
    of fixing non-trivial gate failures.

    Returns True when a retry was scheduled, False when the budget is
    exhausted (caller should fall back to the normal failure path).
    """
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return False

        attempts = feature.metadata.gate_retry
        if attempts >= MAX_GATE_AUTO_RETRIES:
            return False

        gate_phase = feature.find_phase(PhaseName.GATE)
        if not gate_phase:
            return False

        fixing_phase = feature.find_phase(PhaseName.FIXING)
        if fixing_phase is None:
            fixing_phase = PhaseRecord(name=PhaseName.FIXING, status=PhaseStatus.PENDING)
            gate_idx = feature.phases.index(gate_phase)
            feature.phases.insert(gate_idx, fixing_phase)
        else:
            fixing_phase.reset()

        gate_phase.reset()
        next_attempt = attempts + 1
        feature.metadata.gate_retry = next_attempt

        # Record the tier to use for this retry's fixing phase. We persist
        # the canonical ModelTier value (a StrEnum) so state.json stays
        # backend-agnostic; each backend maps it to its own model name.
        tier = _RETRY_TIER_ESCALATION.get(next_attempt)
        feature.metadata.gate_retry_models.append(tier.value if tier else None)

        transition_safe(feature, FeatureStatus.FIXING)
        return True
