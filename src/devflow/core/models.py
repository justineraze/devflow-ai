"""Feature lifecycle models — the persisted domain objects.

This module owns the *feature* domain (Feature, PhaseRecord, PhaseStatus,
PhaseName, PhaseType, FeatureMetadata, WorkflowState, generate_feature_id).

A handful of types are also re-exported here because consumers still
import them from ``models`` rather than from the sibling module:

- :class:`FeatureStatus` from :mod:`devflow.core.state_machine`.
- :class:`ComplexityScore` from :mod:`devflow.core.complexity`.
- :class:`SyncResult` from :mod:`devflow.core.sync_results`.

Anything else (VALID_TRANSITIONS, InvalidTransition, DirtyWorktreeError,
CRITICAL_PATH_PATTERNS, WorkflowDefinition, PhaseDefinition) must be
imported from its canonical module.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from devflow.core.complexity import ComplexityScore
from devflow.core.state_machine import VALID_TRANSITIONS, FeatureStatus, InvalidTransition
from devflow.core.sync_results import SyncResult


class FeatureMetadata(BaseModel):
    """Typed metadata carried by a Feature throughout its lifecycle."""

    feedback: str | None = None
    """User feedback on the previous plan (re-planning flow)."""

    gate_retry: int = 0
    """Number of automatic gate→fixing→gate retry cycles consumed."""

    gate_retry_models: list[str | None] = Field(default_factory=list)
    """Model tier used at each gate retry (e.g. [None, 'sonnet', 'opus']).
    None entries mean "no escalation, let the selector decide"."""

    review_cycles: int = 0
    """Number of review→fix→review cycles consumed (max 2)."""

    archived: bool = False
    """True after devflow sync archives a merged feature."""

    scope: str | None = None
    """Primary module touched (e.g. 'runner', 'gate'). Parsed from the plan's
    Module: line — used as the Conventional Commits scope in commit messages."""

    title: str | None = None
    """Concise title parsed from the plan header (e.g. 'document Pydantic vs
    dataclass convention'). Used instead of the raw description for PR titles."""

    commit_type: str | None = None
    """Conventional Commits type parsed from the plan's Type: line.  Mapped from
    plan types (new-feature→feat, bugfix→fix, refactor→refactor, docs→docs,
    ci→ci, test→test).  Falls back to workflow-based default when absent."""

    complexity: ComplexityScore | None = None
    """Complexity score computed at feature creation (auto-select workflow)."""

    worktree_path: str | None = None
    """Absolute path to the git worktree for this feature, if any.
    None when the feature runs on the current branch."""

    review_reformat_retries: int = 0
    """Number of reviewer reformat retries consumed (max 1)."""

    double_review_done: bool = False
    """True after the second independent review has been scheduled."""

    linear_issue_id: str | None = None
    """Linear issue UUID. Set when synced to Linear."""

    linear_issue_key: str | None = None
    """Linear issue identifier for display (e.g. 'ABC-123')."""

    model_config = {"extra": "allow"}
    """Allow unknown keys so old state.json files deserialise without error."""


class PhaseType(StrEnum):
    """Semantic category for phases — replaces scattered name checks."""

    PLANNING = "planning"
    CODE = "code"
    REVIEW = "review"
    GATE = "gate"


class PhaseStatus(StrEnum):
    """Status of a single phase execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class PhaseName(StrEnum):
    """Canonical phase identifiers, listed in workflow execution order."""

    ARCHITECTURE = "architecture"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    IMPLEMENTING = "implementing"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    GATE = "gate"


class PhaseRecord(BaseModel):
    """Record of a single phase execution within a feature."""

    name: PhaseName
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: str = ""
    error: str = ""
    model: str | None = None

    def start(self) -> None:
        """Mark this phase as in progress."""
        self.status = PhaseStatus.IN_PROGRESS
        self.started_at = datetime.now(UTC)

    def complete(self, output: str = "") -> None:
        """Mark this phase as done."""
        self.status = PhaseStatus.DONE
        self.completed_at = datetime.now(UTC)
        self.output = output

    def reset(self) -> None:
        """Return the phase to its pristine PENDING state."""
        self.status = PhaseStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.output = ""
        self.error = ""

    def fail(self, error: str = "") -> None:
        """Mark this phase as failed."""
        self.status = PhaseStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.error = error


def generate_feature_id(description: str) -> str:
    """Generate a short feature ID from a description.

    Format: ``feat-<slug>-<MMDD>`` where slug is the first 3 words,
    lowercased and stripped of special characters.
    """
    words = re.sub(r"[^a-zA-Z0-9\s]", "", description.lower()).split()
    slug = "-".join(words[:3])
    timestamp = datetime.now(UTC).strftime("%m%d")
    return f"feat-{slug}-{timestamp}" if slug else f"feat-{timestamp}"


class Feature(BaseModel):
    """A tracked feature with its lifecycle state."""

    id: str
    description: str
    prompt: str | None = None
    """Original user prompt when description was summarised by Haiku.
    None when the description *is* the original prompt (short enough)."""
    status: FeatureStatus = FeatureStatus.PENDING
    workflow: str = "standard"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phases: list[PhaseRecord] = Field(default_factory=list)
    metadata: FeatureMetadata = Field(default_factory=FeatureMetadata)
    parent_id: str | None = None
    """ID of the parent epic. None for standalone features and epics themselves."""

    def transition_to(self, target: FeatureStatus) -> None:
        """Transition to a new status, raising InvalidTransition if not allowed."""
        allowed = VALID_TRANSITIONS.get(self.status, frozenset())
        if target not in allowed:
            raise InvalidTransition(self.status, target)
        self.status = target
        self.updated_at = datetime.now(UTC)

    def find_phase(self, name: str | PhaseName) -> PhaseRecord | None:
        """Return the phase with *name* (first match), or None."""
        target = name.value if isinstance(name, PhaseName) else name
        for phase in self.phases:
            if phase.name == target:
                return phase
        return None

    @property
    def current_phase(self) -> PhaseRecord | None:
        """Return the currently active phase, if any."""
        for phase in self.phases:
            if phase.status == PhaseStatus.IN_PROGRESS:
                return phase
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_phase_name(self) -> str | None:
        """Name of the in-progress phase, serialised into state.json.

        Exposed so external consumers (e.g. the post-compact hook) can read
        the active phase from the JSON snapshot without having to walk the
        ``phases`` array themselves.
        """
        current = self.current_phase
        return current.name.value if current else None

    @property
    def is_terminal(self) -> bool:
        """Return True if the feature is done. Failed features can be resumed."""
        return self.status == FeatureStatus.DONE


class WorkflowState(BaseModel):
    """Top-level project state persisted in .devflow/state.json.

    Contains only runtime state (features + timestamps).  Project
    configuration (stack, base_branch, linear, backend) lives in
    ``.devflow/config.yaml`` — see :mod:`devflow.core.config`.
    """

    model_config = {"extra": "ignore"}
    """Ignore legacy config fields (stack, base_branch, linear_team_id)
    that may still be present in old state.json files."""

    version: int = 1
    features: dict[str, Feature] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_feature(self, feature: Feature) -> None:
        """Add a feature to the project state."""
        self.features[feature.id] = feature
        self.updated_at = datetime.now(UTC)

    def get_feature(self, feature_id: str) -> Feature | None:
        """Get a feature by ID, or None if not found."""
        return self.features.get(feature_id)

    def children_of(self, parent_id: str) -> list[Feature]:
        """Return all features whose parent_id matches *parent_id*."""
        return [f for f in self.features.values() if f.parent_id == parent_id]

    def epics(self) -> list[Feature]:
        """Return features that have children (i.e. are epics)."""
        parent_ids = {f.parent_id for f in self.features.values() if f.parent_id}
        return [f for f in self.features.values() if f.id in parent_ids]

    def is_epic(self, feature_id: str) -> bool:
        """Return True if *feature_id* has any child features."""
        return any(f.parent_id == feature_id for f in self.features.values())


__all__ = [
    "VALID_TRANSITIONS",
    "ComplexityScore",
    "Feature",
    "FeatureMetadata",
    "FeatureStatus",
    "InvalidTransition",
    "PhaseName",
    "PhaseRecord",
    "PhaseStatus",
    "PhaseType",
    "SyncResult",
    "WorkflowState",
    "generate_feature_id",
]
