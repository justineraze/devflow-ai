"""Epic management — parent/child feature hierarchy.

An *epic* is a regular Feature that has children (sub-features linked
via ``parent_id``).  Epics don't run phases themselves — they are
containers whose status is derived from the progress of their children.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devflow.core.models import Feature, FeatureStatus, WorkflowState, generate_feature_id
from devflow.core.workflow import load_state, save_state


@dataclass
class EpicProgress:
    """Aggregated progress of an epic's sub-features."""

    total: int
    done: int
    in_progress: int
    failed: int
    pending: int

    @property
    def ratio(self) -> float:
        """Completion ratio (0.0–1.0)."""
        return self.done / self.total if self.total > 0 else 0.0

    @property
    def all_done(self) -> bool:
        return self.total > 0 and self.done == self.total


def epic_progress(state: WorkflowState, epic_id: str) -> EpicProgress:
    """Compute the progress of an epic from its children's statuses."""
    children = state.children_of(epic_id)
    done = sum(1 for c in children if c.status == FeatureStatus.DONE)
    failed = sum(
        1 for c in children
        if c.status in (FeatureStatus.FAILED, FeatureStatus.BLOCKED)
    )
    in_progress = sum(
        1 for c in children
        if c.status not in (
            FeatureStatus.PENDING, FeatureStatus.DONE,
            FeatureStatus.FAILED, FeatureStatus.BLOCKED,
        )
    )
    pending = sum(1 for c in children if c.status == FeatureStatus.PENDING)
    return EpicProgress(
        total=len(children),
        done=done,
        in_progress=in_progress,
        failed=failed,
        pending=pending,
    )


def create_epic(
    description: str,
    sub_descriptions: list[str],
    workflow: str = "standard",
    base: Path | None = None,
) -> tuple[Feature, list[Feature]]:
    """Create an epic and its sub-features in a single transaction.

    The epic itself gets no phases — it's a container.  Each sub-feature
    is a normal feature linked to the epic via ``parent_id``.

    Returns ``(epic, sub_features)``.
    """
    from devflow.core.workflow import create_feature

    state = load_state(base)

    epic_id = generate_feature_id(description)
    epic = Feature(
        id=epic_id,
        description=description,
        status=FeatureStatus.PENDING,
        workflow=workflow,
        phases=[],
    )
    state.add_feature(epic)

    subs: list[Feature] = []
    for sub_desc in sub_descriptions:
        sub = create_feature(state, generate_feature_id(sub_desc), sub_desc, workflow)
        sub.parent_id = epic_id
        subs.append(sub)

    save_state(state, base)
    return epic, subs


def add_sub_feature(
    epic_id: str,
    description: str,
    workflow: str = "standard",
    base: Path | None = None,
) -> Feature:
    """Add a sub-feature to an existing epic."""
    from devflow.core.workflow import create_feature

    state = load_state(base)
    epic = state.get_feature(epic_id)
    if epic is None:
        raise ValueError(f"Epic {epic_id!r} not found")

    sub = create_feature(state, generate_feature_id(description), description, workflow)
    sub.parent_id = epic_id
    save_state(state, base)
    return sub


def check_epic_completion(
    epic_id: str, base: Path | None = None,
) -> bool:
    """If all children of *epic_id* are DONE, mark the epic as DONE.

    Returns True if the epic was transitioned to DONE.
    """
    state = load_state(base)
    epic = state.get_feature(epic_id)
    if epic is None or epic.status == FeatureStatus.DONE:
        return False

    progress = epic_progress(state, epic_id)
    if progress.all_done:
        epic.status = FeatureStatus.DONE
        save_state(state, base)
        return True
    return False
