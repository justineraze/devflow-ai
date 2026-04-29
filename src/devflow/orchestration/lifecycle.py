"""Feature lifecycle — creation, resume, retry, and recovery.

Responsible for one thing: managing the birth and recovery of Feature
objects in the project state. The build loop lives in build.py; the
phase state machine lives in phase_exec.py.

Errors are raised as typed :class:`DevflowError` subclasses so the
caller (CLI or higher-level orchestrator) decides how to render them.
This module performs no I/O on stdout/stderr.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.complexity import ComplexityScore
from devflow.core.config import load_config
from devflow.core.errors import (
    FeatureAlreadyDoneError,
    FeatureNotFailedError,
    FeatureNotFoundError,
)
from devflow.core.models import Feature, PhaseStatus, generate_feature_id
from devflow.core.phases import get_spec
from devflow.core.state_machine import FeatureStatus, InvalidTransition
from devflow.core.workflow import create_feature, load_state, mutate_feature, save_state
from devflow.integrations.complexity import score_complexity
from devflow.integrations.git.smart_messages import generate_feature_title
from devflow.integrations.linear.client import is_configured
from devflow.integrations.linear.sync import create_issue_for_feature


def transition_safe(feature: Feature, target: FeatureStatus) -> bool:
    """Attempt a state transition, returning True if successful."""
    try:
        feature.transition_to(target)
        return True
    except InvalidTransition:
        return False


def _score_workflow(
    description: str, base: Path | None,
) -> tuple[str, ComplexityScore]:
    """Score complexity and return (workflow_name, complexity)."""
    cfg = load_config(base)
    complexity = score_complexity(description, base, workflow_floor=cfg.workflow)
    return complexity.workflow, complexity


def _create_linear_issue_if_configured(
    feature: Feature, base: Path | None,
) -> None:
    """Auto-create a Linear issue for *feature* if the integration is configured.

    Mutates ``feature.metadata`` in place; the resulting ``linear_issue_key``
    is what the caller surfaces to the user.
    """
    linear_team = load_config(base).linear.team
    if not linear_team:
        return
    if is_configured():
        create_issue_for_feature(feature, linear_team)


def start_build(
    description: str,
    workflow_name: str | None = None,
    base: Path | None = None,
) -> Feature:
    """Start a new feature build.

    When *workflow_name* is ``None``, the workflow is auto-selected by scoring
    the feature description and project structure via :func:`score_complexity`.
    The resulting :class:`~devflow.core.complexity.ComplexityScore` is stored
    in ``feature.metadata.complexity`` so callers can render it without
    re-running the scorer.
    """
    state = load_state(base)

    # When the prompt is long, summarise it via Haiku and use the
    # summary for both the feature ID and description.
    prompt: str | None = None
    if len(description) > 100:
        title = generate_feature_title(description)
        prompt = description
        description = title

    feature_id = generate_feature_id(description)

    counter = 1
    original_id = feature_id
    while feature_id in state.features:
        counter += 1
        feature_id = f"{original_id}-{counter}"

    complexity: ComplexityScore | None = None
    if workflow_name is None:
        workflow_name, complexity = _score_workflow(prompt or description, base)

    feature = create_feature(state, feature_id, description, workflow_name)
    if prompt is not None:
        feature.prompt = prompt
    if complexity is not None:
        feature.metadata.complexity = complexity

    _create_linear_issue_if_configured(feature, base)
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
                    transition_safe(feature, get_spec(p.name).feature_status)
            return


def resume_build(
    feature_id: str,
    base: Path | None = None,
) -> Feature:
    """Resume an existing feature build.

    Raises :class:`FeatureNotFoundError` when the ID is unknown and
    :class:`FeatureAlreadyDoneError` when the feature is in a terminal state.
    A failed feature is recovered (its last failed phase resets to pending)
    before being returned.
    """
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            raise FeatureNotFoundError(
                f"✗ Feature {feature_id!r} not found — not in state.json"
                " — Fix: run devflow status to list features"
            )
        if feature.is_terminal:
            raise FeatureAlreadyDoneError(
                f"✗ Feature {feature_id!r} is already {feature.status.value}"
                " — terminal features cannot be resumed"
                " — Fix: start a new build with devflow build"
            )
        if feature.status == FeatureStatus.FAILED:
            _recover_failed_feature(feature)
        return feature


def retry_build(
    feature_id: str,
    base: Path | None = None,
) -> Feature:
    """Retry a failed feature by resetting the failed phase.

    Unlike :func:`resume_build`, this is strictly for FAILED features and
    skips any feedback / re-planning flow. Raises
    :class:`FeatureNotFoundError` when the ID is unknown and
    :class:`FeatureNotFailedError` when the feature is not in FAILED status.
    """
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            raise FeatureNotFoundError(
                f"✗ Feature {feature_id!r} not found — not in state.json"
                " — Fix: run devflow status to list features"
            )
        if feature.status != FeatureStatus.FAILED:
            raise FeatureNotFailedError(
                f"✗ Feature {feature_id!r} is {feature.status.value}, not failed"
                " — only failed features can be retried"
                " — Fix: use devflow build --resume to continue a non-failed feature"
            )
        _recover_failed_feature(feature)
        return feature



def start_do(
    description: str,
    workflow_name: str | None = None,
    base: Path | None = None,
) -> Feature:
    """Start a task on the current branch (no branch, no PR).

    When *workflow_name* is ``None``, the workflow is auto-selected via
    :func:`score_complexity` — exactly like :func:`start_build`.
    The feature is created but no git branch is created; the caller
    handles committing and potential revert.
    """
    return start_build(description, workflow_name=workflow_name, base=base)
