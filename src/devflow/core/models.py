"""Pydantic models and state machine for devflow-ai."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

# Security-sensitive path patterns used by both the complexity scorer and the
# build loop's critical-path detection.  Lives here (core) so both
# integrations/ and orchestration/ can import from core without coupling each
# other.
CRITICAL_PATH_PATTERNS: tuple[str, ...] = (
    "auth", "secret", "token", "crypto", "payment", "billing", "password",
)

# Workflow selection thresholds for ComplexityScore.total (0–12).
_WORKFLOW_THRESHOLDS: list[tuple[int, str]] = [
    (2, "quick"),
    (5, "light"),
    (8, "standard"),
    (12, "full"),
]


def _resolve_workflow(total: int) -> str:
    """Map a complexity total (0–12) to a workflow name."""
    for threshold, name in _WORKFLOW_THRESHOLDS:
        if total <= threshold:
            return name
    return "full"


class ComplexityScore(BaseModel):
    """Complexity score for a feature across four dimensions (each 0–3).

    ``workflow`` is resolved once at construction time and stored as a plain
    field so it survives JSON round-trips and never drifts if thresholds change.
    """

    files_touched: int = Field(default=0, ge=0, le=3)
    """Number of files expected to be modified (heuristic, 0–3)."""

    integrations: int = Field(default=0, ge=0, le=3)
    """External systems involved: API, DB, webhook, OAuth… (0–3)."""

    security: int = Field(default=0, ge=0, le=3)
    """Security-sensitive surface area: auth, tokens, crypto… (0–3)."""

    scope: int = Field(default=0, ge=0, le=3)
    """Breadth of the change: tweak vs. new module vs. rewrite (0–3)."""

    workflow: str = ""
    """Workflow resolved from total at construction time (never recomputed)."""

    def model_post_init(self, __context: object) -> None:
        """Resolve workflow from total once, at construction time."""
        if not self.workflow:
            object.__setattr__(self, "workflow", _resolve_workflow(self.total))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        """Sum of all four dimension scores (0–12)."""
        return self.files_touched + self.integrations + self.security + self.scope


class FeatureMetadata(BaseModel):
    """Typed metadata carried by a Feature throughout its lifecycle."""

    feedback: str | None = None
    """User feedback on the previous plan (re-planning flow)."""

    gate_retry: int = 0
    """Number of automatic gate→fixing→gate retry cycles consumed."""

    gate_retry_models: list[str] = Field(default_factory=list)
    """Model tier used at each gate retry (e.g. ['sonnet', 'sonnet', 'opus'])."""

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

    linear_issue_id: str | None = None
    """Linear issue UUID. Set when synced to Linear."""

    linear_issue_key: str | None = None
    """Linear issue identifier for display (e.g. 'ABC-123')."""

    model_config = {"extra": "allow"}
    """Allow unknown keys so old state.json files deserialise without error."""


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
# Every non-terminal state can also fall into BLOCKED (waiting on user)
# or FAILED (recoverable via --resume) — listed inline below for one
# truth-table at a glance, no post-init mutation required.
_RECOVERY: frozenset[FeatureStatus] = frozenset(
    {FeatureStatus.BLOCKED, FeatureStatus.FAILED},
)
VALID_TRANSITIONS: dict[FeatureStatus, set[FeatureStatus]] = {
    FeatureStatus.PENDING: {
        FeatureStatus.PLANNING,
        FeatureStatus.IMPLEMENTING,
        *_RECOVERY,
    },
    # PLANNING can skip plan_review in workflows that don't include it.
    FeatureStatus.PLANNING: {
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        *_RECOVERY,
    },
    FeatureStatus.PLAN_REVIEW: {
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.PLANNING,
        *_RECOVERY,
    },
    # IMPLEMENTING can skip review in light/quick workflows.
    FeatureStatus.IMPLEMENTING: {
        FeatureStatus.REVIEWING,
        FeatureStatus.GATE,
        *_RECOVERY,
    },
    FeatureStatus.REVIEWING: {
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
        FeatureStatus.DONE,
        *_RECOVERY,
    },
    FeatureStatus.FIXING: {
        FeatureStatus.REVIEWING,
        FeatureStatus.GATE,
        FeatureStatus.DONE,
        *_RECOVERY,
    },
    FeatureStatus.GATE: {
        FeatureStatus.DONE,
        FeatureStatus.FIXING,
        *_RECOVERY,
    },
    FeatureStatus.DONE: set(),
    FeatureStatus.BLOCKED: {
        FeatureStatus.PENDING,
        FeatureStatus.PLANNING,
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
        FeatureStatus.BLOCKED,
        FeatureStatus.FAILED,
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


class InvalidTransition(Exception):
    """Raised when a feature status transition is not allowed."""

    def __init__(self, current: FeatureStatus, target: FeatureStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value!r} to {target.value!r}")


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
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise InvalidTransition(self.status, target)
        self.status = target
        self.updated_at = datetime.now(UTC)

    def find_phase(self, name: str | PhaseName) -> PhaseRecord | None:
        """Return the phase with *name* (first match), or None.

        Replaces the ``next(p for p in feature.phases if p.name == name)``
        / ``for phase in feature.phases: if phase.name == name`` pattern
        sprinkled across ``phase_exec.py`` and ``build.py``.
        """
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

    @property
    def is_terminal(self) -> bool:
        """Return True if the feature is done. Failed features can be resumed."""
        return self.status == FeatureStatus.DONE


class WorkflowState(BaseModel):
    """Top-level project state persisted in .devflow/state.json."""

    version: int = 1
    stack: str | None = None
    base_branch: str = "main"
    linear_team_id: str | None = None
    """Linear team ID (e.g. 'ABC'). Set via devflow init --linear-team. Optional."""
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
        return [f for fid, f in self.features.items() if fid in parent_ids]

    def is_epic(self, feature_id: str) -> bool:
        """Return True if *feature_id* has any child features."""
        return any(f.parent_id == feature_id for f in self.features.values())


class PhaseDefinition(BaseModel):
    """Definition of a phase in a workflow YAML file."""

    name: PhaseName
    agent: str = ""
    description: str = ""
    required: bool = True
    timeout: int = 300
    model: str | None = None


class WorkflowDefinition(BaseModel):
    """Definition of a complete workflow loaded from YAML."""

    name: str
    description: str = ""
    phases: list[PhaseDefinition] = Field(default_factory=list)
