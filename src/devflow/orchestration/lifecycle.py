"""Feature lifecycle — creation, resume, retry, and recovery.

Responsible for one thing: managing the birth and recovery of Feature
objects in the project state. The build loop lives in build.py; the
phase state machine lives in phase_exec.py.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.complexity import ComplexityScore
from devflow.core.config import load_config
from devflow.core.console import console
from devflow.core.models import Feature, PhaseStatus, generate_feature_id
from devflow.core.phases import get_spec
from devflow.core.state_machine import FeatureStatus, InvalidTransition
from devflow.core.workflow import create_feature, load_state, mutate_feature, save_state
from devflow.integrations.complexity import score_complexity
from devflow.integrations.git.smart_messages import generate_feature_title
from devflow.integrations.linear.client import is_configured
from devflow.integrations.linear.sync import create_issue_for_feature

# Keep the private alias for backwards compatibility (tests, epics.py).
_generate_feature_id = generate_feature_id


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
    method_label = "scored by LLM" if complexity.method == "llm" else "heuristic fallback"
    console.print(
        f"[dim]Complexity: "
        f"files={complexity.files_touched} "
        f"integrations={complexity.integrations} "
        f"security={complexity.security} "
        f"scope={complexity.scope} "
        f"→ {complexity.workflow} ({method_label})[/dim]"
    )
    return complexity.workflow, complexity


def _create_linear_issue_if_configured(
    feature: Feature, base: Path | None,
) -> None:
    """Auto-create a Linear issue for *feature* if the integration is configured."""
    linear_team = load_config(base).linear.team
    if not linear_team:
        return
    if is_configured():
        key = create_issue_for_feature(feature, linear_team)
        if key:
            console.print(f"[dim]Linear: {key}[/dim]")


def start_build(
    description: str,
    workflow_name: str | None = None,
    base: Path | None = None,
) -> Feature:
    """Start a new feature build.

    When *workflow_name* is ``None``, the workflow is auto-selected by scoring
    the feature description and project structure via :func:`score_complexity`.
    The resulting :class:`~devflow.core.models.ComplexityScore` is stored in
    ``feature.metadata.complexity`` for display in ``devflow status``.
    """
    state = load_state(base)

    # When the prompt is long, summarise it via Haiku and use the
    # summary for both the feature ID and description.
    prompt: str | None = None
    if len(description) > 100:
        title = generate_feature_title(description)
        prompt = description
        description = title

    feature_id = _generate_feature_id(description)

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
) -> Feature | None:
    """Resume an existing feature build.

    If the feature is failed, resets the failed phase to pending
    so it can be retried.
    """
    with mutate_feature(feature_id, base) as feature:
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
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            console.print(f"[red]Feature {feature_id!r} not found.[/red]")
            return None

        if feature.status != FeatureStatus.FAILED:
            console.print(
                f"[yellow]Feature {feature_id!r} is {feature.status.value}, not failed.[/yellow]"
            )
            return None

        _recover_failed_feature(feature)
        console.print(f"[cyan]Retrying {feature_id} — reset failed phase to pending.[/cyan]")
        return feature


def start_fix(description: str, base: Path | None = None) -> Feature:
    """Start a bug fix using the quick workflow (no planning phase).

    Always uses ``quick`` — complexity scoring is intentionally skipped.
    """
    return start_build(description, workflow_name="quick", base=base)


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
