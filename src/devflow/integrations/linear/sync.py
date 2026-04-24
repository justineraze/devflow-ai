"""Bidirectional sync between devflow features and Linear issues.

Sync is opt-in: only runs when ``LINEAR_API_KEY`` is set and the
project has a ``linear_team_id`` in state.json.

Status mapping (devflow → Linear workflow state *type*):
    pending       → backlog
    planning      → unstarted
    implementing  → started
    reviewing     → started
    fixing        → started
    gate          → started
    done          → completed
    blocked       → canceled
    failed        → canceled
"""

from __future__ import annotations

import logging
from pathlib import Path

from devflow.core.models import Feature, FeatureStatus
from devflow.core.workflow import load_state, save_state
from devflow.integrations.linear.client import (
    LinearError,
    create_issue,
    get_workflow_states,
    is_configured,
    update_issue_state,
)

log = logging.getLogger(__name__)

# Map devflow FeatureStatus → Linear workflow state type.
_STATUS_TO_LINEAR_TYPE: dict[FeatureStatus, str] = {
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


class SyncResult:
    """Accumulates sync outcomes for reporting."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.updated: list[str] = []
        self.errors: list[str] = []
        self.skipped: int = 0

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated) + self.skipped


def _resolve_state_id(
    team_id: str, target_type: str, _cache: dict[str, dict[str, str]] | None = None,
) -> str | None:
    """Find the Linear workflow state ID for a given type (backlog, started, etc.).

    Caches the state list per team to avoid redundant API calls.
    """
    if _cache is None:
        _cache = {}
    if team_id not in _cache:
        states = get_workflow_states(team_id)
        _cache[team_id] = {s["type"]: s["id"] for s in states}
    return _cache[team_id].get(target_type)


def sync_feature_to_linear(
    feature: Feature,
    team_id: str,
    state_cache: dict[str, dict[str, str]],
    *,
    parent_linear_id: str | None = None,
) -> str | None:
    """Create or update a Linear issue for *feature*.

    Returns the action taken: 'created', 'updated', or None (no-op).
    Sets ``feature.metadata.linear_issue_id`` (UUID) and
    ``feature.metadata.linear_issue_key`` (identifier) on creation.
    """
    target_type = _STATUS_TO_LINEAR_TYPE.get(feature.status, "backlog")

    if feature.metadata.linear_issue_id is None:
        # Create new issue.
        issue = create_issue(
            team_id,
            title=feature.metadata.title or feature.description,
            description=f"devflow feature: `{feature.id}`",
            parent_id=parent_linear_id,
        )
        # Store UUID for API calls, identifier for display.
        feature.metadata.linear_issue_id = issue.get("id")
        feature.metadata.linear_issue_key = issue.get("identifier")
        # Also move to the right state.
        state_id = _resolve_state_id(team_id, target_type, state_cache)
        if state_id and feature.metadata.linear_issue_id:
            update_issue_state(feature.metadata.linear_issue_id, state_id)
        return "created"

    # Update existing issue state.
    state_id = _resolve_state_id(team_id, target_type, state_cache)
    if state_id is None:
        log.warning(
            "No Linear workflow state of type %r for team %s — skipping update",
            target_type, team_id,
        )
        return None
    update_issue_state(feature.metadata.linear_issue_id, state_id)
    return "updated"


def sync_single_feature(
    feature: Feature,
    team_id: str,
    base: Path | None = None,
) -> None:
    """Sync a single feature's status to Linear (best-effort).

    Used by the build loop after finalize/fail to keep Linear in sync.
    Catches all errors silently — Linear must never block the build.
    """
    if not is_configured() or not feature.metadata.linear_issue_id:
        return
    try:
        state_cache: dict[str, dict[str, str]] = {}
        sync_feature_to_linear(feature, team_id, state_cache)
    except LinearError as exc:
        log.warning("Linear sync failed for %s: %s", feature.id, exc)


def create_issue_for_feature(
    feature: Feature,
    team_id: str,
) -> str | None:
    """Create a Linear issue for a new feature (best-effort).

    Returns the identifier (e.g. 'ABC-123') or None if creation fails.
    Sets ``linear_issue_id`` and ``linear_issue_key`` on the feature
    metadata. Never raises — catches all Linear errors.
    """
    if not is_configured():
        return None
    try:
        issue = create_issue(
            team_id,
            title=feature.metadata.title or feature.description,
            description=f"devflow feature: `{feature.id}`",
        )
        feature.metadata.linear_issue_id = issue.get("id")
        feature.metadata.linear_issue_key = issue.get("identifier")
        return feature.metadata.linear_issue_key
    except LinearError as exc:
        log.warning("Linear issue creation failed for %s: %s", feature.id, exc)
        return None


def sync_all(base: Path | None = None) -> SyncResult:
    """Sync all active features to Linear.

    Skips features that are archived. Creates issues for features
    without a Linear ID, updates state for features that already have one.

    Returns a SyncResult with counts of created/updated/errors.
    """
    result = SyncResult()

    if not is_configured():
        result.errors.append("LINEAR_API_KEY not set")
        return result

    from devflow.core.config import load_config

    config = load_config(base)
    if not config.linear.team:
        result.errors.append(
            "No linear team configured. Run: devflow install --linear-team <ID>"
        )
        return result

    state = load_state(base)
    team_id = config.linear.team
    state_cache: dict[str, dict[str, str]] = {}

    # First pass: sync epics (so we have their Linear IDs for children).
    for feature in state.features.values():
        if feature.metadata.archived:
            result.skipped += 1
            continue
        if not state.is_epic(feature.id):
            continue
        try:
            action = sync_feature_to_linear(feature, team_id, state_cache)
            if action == "created":
                result.created.append(feature.id)
            elif action == "updated":
                result.updated.append(feature.id)
        except LinearError as exc:
            result.errors.append(f"{feature.id}: {exc}")

    # Second pass: sync regular features and sub-features.
    for feature in state.features.values():
        if feature.metadata.archived:
            continue
        if state.is_epic(feature.id):
            continue  # Already synced.

        parent_linear_id = None
        if feature.parent_id:
            parent = state.get_feature(feature.parent_id)
            if parent and parent.metadata.linear_issue_id:
                parent_linear_id = parent.metadata.linear_issue_id

        try:
            action = sync_feature_to_linear(
                feature, team_id, state_cache,
                parent_linear_id=parent_linear_id,
            )
            if action == "created":
                result.created.append(feature.id)
            elif action == "updated":
                result.updated.append(feature.id)
        except LinearError as exc:
            result.errors.append(f"{feature.id}: {exc}")

    save_state(state, base)
    return result
