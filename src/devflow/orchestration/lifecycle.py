"""Feature lifecycle — creation, resume, retry, and recovery.

Responsible for one thing: managing the birth and recovery of Feature
objects in the project state. The build loop lives in build.py; the
phase state machine lives in phase_exec.py.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from devflow.core.models import Feature, FeatureStatus, PhaseStatus
from devflow.core.phases import get_spec
from devflow.core.workflow import create_feature, load_state, save_state
from devflow.ui.console import console


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


def _recover_failed_feature(feature: Feature) -> None:
    """Reset a failed feature so it can be retried.

    Finds the last failed phase, resets it to pending, and sets
    the feature status to the appropriate state for that phase.
    """
    for phase in reversed(feature.phases):
        if phase.status == PhaseStatus.FAILED:
            phase.reset()

            feature.status = FeatureStatus.PENDING
            for p in feature.phases:
                if p.name == phase.name:
                    break
                if p.status == PhaseStatus.DONE:
                    _transition_safe(feature, get_spec(p.name).feature_status)
            return


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

    if feature.status == FeatureStatus.FAILED:
        _recover_failed_feature(feature)
        save_state(state, base)
        console.print(f"[cyan]Recovering {feature_id} from failed state.[/cyan]")

    return feature


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
