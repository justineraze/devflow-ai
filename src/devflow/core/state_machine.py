"""Feature state machine — statuses and valid transitions.

A :class:`Feature` advances through a sequence of statuses; every move
is validated against :data:`VALID_TRANSITIONS` to guarantee no phase is
skipped or revisited illegally.

Two recovery states allow a feature to escape a stuck path:

- :attr:`FeatureStatus.BLOCKED` — explicit pause, can resume to any state.
- :attr:`FeatureStatus.FAILED`  — recoverable via ``--resume``; can return
  to any non-terminal state.

Only :attr:`FeatureStatus.DONE` is terminal.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


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


# Recovery states — every non-terminal status can fall into BLOCKED
# (waiting on user) or FAILED (recoverable via --resume).
_RECOVERY: frozenset[FeatureStatus] = frozenset(
    {FeatureStatus.BLOCKED, FeatureStatus.FAILED},
)

_VALID_TRANSITIONS_RAW: dict[FeatureStatus, frozenset[FeatureStatus]] = {
    FeatureStatus.PENDING: frozenset({
        FeatureStatus.PLANNING,
        FeatureStatus.IMPLEMENTING,
        *_RECOVERY,
    }),
    # PLANNING can skip plan_review in workflows that don't include it.
    FeatureStatus.PLANNING: frozenset({
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        *_RECOVERY,
    }),
    FeatureStatus.PLAN_REVIEW: frozenset({
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.PLANNING,
        *_RECOVERY,
    }),
    # IMPLEMENTING can skip review in light/quick workflows.
    FeatureStatus.IMPLEMENTING: frozenset({
        FeatureStatus.REVIEWING,
        FeatureStatus.GATE,
        *_RECOVERY,
    }),
    FeatureStatus.REVIEWING: frozenset({
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
        FeatureStatus.DONE,
        *_RECOVERY,
    }),
    FeatureStatus.FIXING: frozenset({
        FeatureStatus.REVIEWING,
        FeatureStatus.GATE,
        FeatureStatus.DONE,
        *_RECOVERY,
    }),
    FeatureStatus.GATE: frozenset({
        FeatureStatus.DONE,
        FeatureStatus.FIXING,
        *_RECOVERY,
    }),
    FeatureStatus.DONE: frozenset(),
    FeatureStatus.BLOCKED: frozenset({
        FeatureStatus.PENDING,
        FeatureStatus.PLANNING,
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
        FeatureStatus.BLOCKED,
        FeatureStatus.FAILED,
    }),
    # FAILED is recoverable via --resume: can go back to any non-terminal state.
    FeatureStatus.FAILED: frozenset({
        FeatureStatus.PENDING,
        FeatureStatus.PLANNING,
        FeatureStatus.PLAN_REVIEW,
        FeatureStatus.IMPLEMENTING,
        FeatureStatus.REVIEWING,
        FeatureStatus.FIXING,
        FeatureStatus.GATE,
    }),
}

VALID_TRANSITIONS: Mapping[FeatureStatus, frozenset[FeatureStatus]] = MappingProxyType(
    _VALID_TRANSITIONS_RAW,
)
"""Frozen lookup: current status → set of allowed next statuses."""


class InvalidTransition(Exception):
    """Raised when a feature status transition is not allowed."""

    def __init__(self, current: FeatureStatus, target: FeatureStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value!r} to {target.value!r}")


__all__ = [
    "VALID_TRANSITIONS",
    "FeatureStatus",
    "InvalidTransition",
]
