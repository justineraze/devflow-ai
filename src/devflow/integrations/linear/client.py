"""Thin GraphQL client for the Linear API.

Uses only stdlib (urllib) — no external dependency. All methods return
plain dicts parsed from JSON responses. Raises ``LinearError`` on API
or network failures.

Authentication: ``LINEAR_API_KEY`` environment variable (personal API key
or OAuth token). When missing, ``is_configured()`` returns False and all
mutating methods raise ``LinearError``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearError(Exception):
    """Raised on Linear API errors or missing configuration."""


def _api_key(base: Path | None = None) -> str | None:
    """Resolve the Linear API key.

    Lookup order:
    1. ``$LINEAR_API_KEY`` environment variable.
    2. ``.devflow/linear.key`` file in the current project
       (already gitignored via ``.devflow/``).
    """
    from_env = os.environ.get("LINEAR_API_KEY")
    if from_env:
        return from_env.strip()

    root = base or Path.cwd()
    key_file = root / ".devflow" / "linear.key"
    if key_file.is_file():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            return content

    return None


def is_configured() -> bool:
    """Return True when the API key is available."""
    return bool(_api_key())


def _request(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a GraphQL request against Linear's API."""
    key = _api_key()
    if not key:
        raise LinearError(
            "Linear API key not found. Set LINEAR_API_KEY env var "
            "or write it to .devflow/linear.key"
        )

    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=body,
        headers={
            "Authorization": key,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")[:500]
        raise LinearError(f"Linear API HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise LinearError(f"Linear API unreachable: {exc.reason}") from exc

    errors = data.get("errors", [])
    if errors:
        msg = errors[0].get("message", "Unknown Linear API error")
        raise LinearError(f"Linear GraphQL error: {msg}")

    payload: dict[str, Any] = data.get("data", {})
    return payload


# ── Queries ─────────────────────────────────────────────────────────


def get_teams() -> list[dict[str, str]]:
    """List teams the API key has access to.

    Returns ``[{"id": "...", "key": "ABC", "name": "..."}]``.
    """
    data = _request("""
        query { teams { nodes { id key name } } }
    """)
    nodes: list[dict[str, str]] = data.get("teams", {}).get("nodes", [])
    return nodes


def get_issue(issue_id: str) -> dict[str, Any] | None:
    """Fetch a single issue by its identifier (e.g. 'ABC-123').

    Returns the issue dict or None if not found.
    """
    data = _request("""
        query($id: String!) {
            issue(id: $id) {
                id identifier title state { name } priority url
            }
        }
    """, {"id": issue_id})
    issue: dict[str, Any] | None = data.get("issue")
    return issue


def search_issues(
    team_id: str, *, query: str = "", limit: int = 20,
) -> list[dict[str, Any]]:
    """Search issues in a team. Empty *query* returns recent issues."""
    data = _request("""
        query($teamId: String!, $limit: Int!) {
            issues(
                filter: { team: { id: { eq: $teamId } } }
                first: $limit
                orderBy: updatedAt
            ) {
                nodes {
                    id identifier title
                    state { name }
                    priority url
                    labels { nodes { name } }
                }
            }
        }
    """, {"teamId": team_id, "limit": limit})
    nodes: list[dict[str, Any]] = data.get("issues", {}).get("nodes", [])
    return nodes


def get_workflow_states(team_id: str) -> list[dict[str, str]]:
    """List workflow states for a team (Todo, In Progress, Done, etc.)."""
    data = _request("""
        query($teamId: String!) {
            workflowStates(
                filter: { team: { id: { eq: $teamId } } }
            ) {
                nodes { id name type }
            }
        }
    """, {"teamId": team_id})
    nodes: list[dict[str, str]] = data.get("workflowStates", {}).get("nodes", [])
    return nodes


# ── Mutations ───────────────────────────────────────────────────────


def create_issue(
    team_id: str,
    title: str,
    description: str = "",
    *,
    parent_id: str | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    """Create an issue in a Linear team.

    Returns the created issue dict with ``id``, ``identifier``, ``url``.
    *parent_id* is the Linear issue UUID for sub-issues (epics).
    """
    variables: dict[str, Any] = {
        "teamId": team_id,
        "title": title,
        "description": description,
        "priority": priority,
    }
    if parent_id:
        variables["parentId"] = parent_id

    data = _request("""
        mutation(
            $teamId: String!,
            $title: String!,
            $description: String,
            $priority: Int,
            $parentId: String
        ) {
            issueCreate(input: {
                teamId: $teamId,
                title: $title,
                description: $description,
                priority: $priority,
                parentId: $parentId
            }) {
                issue { id identifier title url }
            }
        }
    """, variables)
    issue: dict[str, Any] = data.get("issueCreate", {}).get("issue", {})
    return issue


def update_issue_state(
    issue_id: str, state_id: str,
) -> dict[str, Any]:
    """Update an issue's workflow state (e.g. move to 'In Progress')."""
    data = _request("""
        mutation($issueId: String!, $stateId: String!) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) {
                issue { id identifier state { name } }
            }
        }
    """, {"issueId": issue_id, "stateId": state_id})
    issue: dict[str, Any] = data.get("issueUpdate", {}).get("issue", {})
    return issue
