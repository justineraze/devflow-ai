"""LinearTracker — IssueTracker implementation backed by Linear's GraphQL API."""

from __future__ import annotations

from pathlib import Path

import structlog

from devflow.core.state_machine import FeatureStatus
from devflow.integrations.linear.client import (
    LinearError,
    create_issue,
    get_workflow_states,
    is_configured,
    update_issue_state,
)

_log = structlog.get_logger(__name__)


class _StatusMapper:
    """Maps FeatureStatus → Linear workflow state ID for a given team."""

    # FeatureStatus → Linear workflow state *type* string.
    _TYPE_MAP: dict[FeatureStatus, str] = {
        FeatureStatus.PENDING: "backlog",
        FeatureStatus.PLANNING: "unstarted",
        FeatureStatus.PLAN_REVIEW: "unstarted",
        FeatureStatus.IMPLEMENTING: "started",
        FeatureStatus.REVIEWING: "started",
        FeatureStatus.FIXING: "started",
        FeatureStatus.GATE: "started",
        FeatureStatus.DONE: "completed",
        FeatureStatus.BLOCKED: "canceled",
        FeatureStatus.FAILED: "canceled",
    }

    def __init__(self, team_id: str) -> None:
        self._team_id = team_id
        self._cache: dict[str, str] | None = None

    def _ensure_cache(self) -> dict[str, str]:
        if self._cache is None:
            states = get_workflow_states(self._team_id)
            self._cache = {s["type"]: s["id"] for s in states}
        return self._cache

    def resolve(self, status: FeatureStatus) -> str | None:
        """Return the Linear state ID for a devflow FeatureStatus."""
        target_type = self._TYPE_MAP.get(status, "backlog")
        return self._ensure_cache().get(target_type)


class LinearTracker:
    """IssueTracker implementation for Linear."""

    def __init__(self, team_id: str, base: Path | None = None) -> None:
        self._team_id = team_id
        self._base = base
        self._mapper = _StatusMapper(team_id)

    @property
    def name(self) -> str:
        return "Linear"

    def check_available(self) -> tuple[bool, str]:
        if not is_configured():
            return False, "LINEAR_API_KEY not set"
        return True, f"Linear configured (team: {self._team_id})"

    def create_issue(
        self,
        *,
        title: str,
        description: str,
        parent_id: str | None = None,
    ) -> str:
        issue = create_issue(
            self._team_id,
            title=title,
            description=description,
            parent_id=parent_id,
        )
        identifier: str = issue.get("identifier", "")
        issue_uuid = issue.get("id", "")

        # Move to initial state.
        state_id = self._mapper.resolve(FeatureStatus.PENDING)
        if state_id and issue_uuid:
            try:
                update_issue_state(issue_uuid, state_id)
            except LinearError as exc:
                _log.warning("Failed to set initial state for %s: %s", identifier, exc)

        return identifier

    def update_status(
        self,
        *,
        issue_id: str,
        status: FeatureStatus,
    ) -> None:
        state_id = self._mapper.resolve(status)
        if state_id is None:
            _log.warning(
                "No Linear workflow state for status %r — skipping update",
                status,
            )
            return
        update_issue_state(issue_id, state_id)

    def link_pr(self, *, issue_id: str, pr_url: str) -> None:
        pass
