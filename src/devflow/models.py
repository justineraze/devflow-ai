"""Pydantic models and state machine for devflow-ai."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PhaseStatus(StrEnum):
    """Status of a single phase execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class FeatureStatus(StrEnum):
    """Lifecycle status of a feature."""

    PENDING = "pending"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    IMPLEMENTING = "implementing"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    GATE = "gate"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


# Valid transitions: current_status -> set of allowed next statuses.
# "blocked" can be reached from any non-terminal state.
# "failed" is terminal — no transitions out.
VALID_TRANSITIONS: dict[FeatureStatus, set[FeatureStatus]] = {
    FeatureStatus.PENDING: {FeatureStatus.PLANNING, FeatureStatus.IMPLEMENTING},
    FeatureStatus.PLANNING: {FeatureStatus.PLAN_REVIEW},
    FeatureStatus.PLAN_REVIEW: {FeatureStatus.IMPLEMENTING, FeatureStatus.PLANNING},
    FeatureStatus.IMPLEMENTING: {FeatureStatus.REVIEWING, FeatureStatus.GATE},
    FeatureStatus.REVIEWING: {FeatureStatus.FIXING, FeatureStatus.GATE},
    FeatureStatus.FIXING: {FeatureStatus.REVIEWING, FeatureStatus.GATE},
    FeatureStatus.GATE: {FeatureStatus.DONE, FeatureStatus.FIXING},
    FeatureStatus.DONE: set(),
    FeatureStatus.BLOCKED: {
        FeatureStatus.PENDING,
        FeatureStatus.PLANNING,
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
    },
    # FAILED is recoverable via --resume: can go back to any non-terminal state.
    FeatureStatus.FAILED: {
        FeatureStatus.PENDING,
        FeatureStatus.PLANNING,
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
    },
}

# Any non-terminal state can transition to BLOCKED or FAILED.
_NON_TERMINAL = {s for s, t in VALID_TRANSITIONS.items() if t or s == FeatureStatus.BLOCKED}
for _status in _NON_TERMINAL:
    VALID_TRANSITIONS[_status].add(FeatureStatus.BLOCKED)
    VALID_TRANSITIONS[_status].add(FeatureStatus.FAILED)


class InvalidTransition(Exception):
    """Raised when a feature status transition is not allowed."""

    def __init__(self, current: FeatureStatus, target: FeatureStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value!r} to {target.value!r}")


class PhaseRecord(BaseModel):
    """Record of a single phase execution within a feature."""

    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: str = ""
    error: str = ""

    def start(self) -> None:
        """Mark this phase as in progress."""
        self.status = PhaseStatus.IN_PROGRESS
        self.started_at = datetime.now(UTC)

    def complete(self, output: str = "") -> None:
        """Mark this phase as done."""
        self.status = PhaseStatus.DONE
        self.completed_at = datetime.now(UTC)
        self.output = output

    def fail(self, error: str = "") -> None:
        """Mark this phase as failed."""
        self.status = PhaseStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.error = error


class Feature(BaseModel):
    """A tracked feature with its lifecycle state."""

    id: str
    description: str
    status: FeatureStatus = FeatureStatus.PENDING
    workflow: str = "standard"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phases: list[PhaseRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def transition_to(self, target: FeatureStatus) -> None:
        """Transition to a new status, raising InvalidTransition if not allowed."""
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise InvalidTransition(self.status, target)
        self.status = target
        self.updated_at = datetime.now(UTC)

    @property
    def current_phase(self) -> PhaseRecord | None:
        """Return the currently active phase, if any."""
        for phase in self.phases:
            if phase.status == PhaseStatus.IN_PROGRESS:
                return phase
        return None

    @property
    def is_terminal(self) -> bool:
        """Return True if the feature is done. Failed features can be resumed."""
        return self.status == FeatureStatus.DONE


class WorkflowState(BaseModel):
    """Top-level project state persisted in .devflow/state.json."""

    version: int = 1
    stack: str | None = None
    features: dict[str, Feature] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_feature(self, feature: Feature) -> None:
        """Add a feature to the project state."""
        self.features[feature.id] = feature
        self.updated_at = datetime.now(UTC)

    def get_feature(self, feature_id: str) -> Feature | None:
        """Get a feature by ID, or None if not found."""
        return self.features.get(feature_id)


class PhaseDefinition(BaseModel):
    """Definition of a phase in a workflow YAML file."""

    name: str
    agent: str = ""
    description: str = ""
    required: bool = True
    timeout: int = 300


class WorkflowDefinition(BaseModel):
    """Definition of a complete workflow loaded from YAML."""

    name: str
    description: str = ""
    phases: list[PhaseDefinition] = Field(default_factory=list)
