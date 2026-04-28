"""IssueTracker protocol — abstraction for issue/project trackers.

Consumers type their dependency as ``IssueTracker``, never a concrete
implementation.  Linear is the built-in tracker; Jira and others are
future plugins discovered via ``entry_points``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from devflow.core.state_machine import FeatureStatus


@runtime_checkable
class IssueTracker(Protocol):
    """Protocol that every issue tracker must implement."""

    @property
    def name(self) -> str:
        """Human-readable tracker name (e.g. 'Linear')."""
        ...

    def check_available(self) -> tuple[bool, str]:
        """Verify the tracker is configured and reachable.

        Returns ``(ok, message)`` — *message* is a status string on
        success or an error description on failure.
        """
        ...

    def create_issue(
        self,
        *,
        title: str,
        description: str,
        parent_id: str | None = None,
    ) -> str:
        """Create an issue and return its display key (e.g. 'ABC-123').

        *parent_id* is the tracker-native parent identifier for sub-issue
        linking (epics).  Ignored by trackers that don't support hierarchy.
        """
        ...

    def update_status(
        self,
        *,
        issue_id: str,
        status: FeatureStatus,
    ) -> None:
        """Update an issue's status to reflect the devflow feature status.

        Each tracker maps ``FeatureStatus`` values to its own workflow
        states internally.
        """
        ...

    def link_pr(self, *, issue_id: str, pr_url: str) -> None:
        """Attach a pull-request URL to an issue.

        Trackers that don't support PR linking should no-op silently.
        """
        ...
