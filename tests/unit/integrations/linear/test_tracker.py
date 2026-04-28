"""Tests for devflow.integrations.linear.tracker — LinearTracker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from devflow.core.state_machine import FeatureStatus
from devflow.core.tracker import IssueTracker
from devflow.integrations.linear.tracker import LinearTracker


@pytest.fixture()
def tracker() -> LinearTracker:
    return LinearTracker(team_id="team-123")


class TestLinearTrackerProtocol:
    def test_satisfies_issue_tracker(self, tracker: LinearTracker) -> None:
        assert isinstance(tracker, IssueTracker)

    def test_name(self, tracker: LinearTracker) -> None:
        assert tracker.name == "Linear"


class TestCheckAvailable:
    @patch("devflow.integrations.linear.tracker.is_configured", return_value=True)
    def test_available(self, _: MagicMock, tracker: LinearTracker) -> None:
        ok, msg = tracker.check_available()
        assert ok is True
        assert "team-123" in msg

    @patch("devflow.integrations.linear.tracker.is_configured", return_value=False)
    def test_unavailable(self, _: MagicMock, tracker: LinearTracker) -> None:
        ok, msg = tracker.check_available()
        assert ok is False
        assert "not set" in msg.lower()


class TestCreateIssue:
    @patch("devflow.integrations.linear.tracker.update_issue_state")
    @patch("devflow.integrations.linear.tracker.get_workflow_states")
    @patch("devflow.integrations.linear.tracker.create_issue")
    def test_returns_identifier(
        self,
        mock_create: MagicMock,
        mock_states: MagicMock,
        mock_update: MagicMock,
        tracker: LinearTracker,
    ) -> None:
        mock_create.return_value = {"id": "uuid-1", "identifier": "ABC-42"}
        mock_states.return_value = [{"type": "backlog", "id": "state-bl"}]

        key = tracker.create_issue(title="Test", description="desc")
        assert key == "ABC-42"
        mock_create.assert_called_once()


class TestUpdateStatus:
    @patch("devflow.integrations.linear.tracker.update_issue_state")
    @patch("devflow.integrations.linear.tracker.get_workflow_states")
    def test_maps_status_to_linear_state(
        self,
        mock_states: MagicMock,
        mock_update: MagicMock,
        tracker: LinearTracker,
    ) -> None:
        mock_states.return_value = [
            {"type": "started", "id": "state-started"},
            {"type": "completed", "id": "state-done"},
        ]
        tracker.update_status(issue_id="uuid-1", status=FeatureStatus.IMPLEMENTING)
        mock_update.assert_called_once_with("uuid-1", "state-started")

    @patch("devflow.integrations.linear.tracker.update_issue_state")
    @patch("devflow.integrations.linear.tracker.get_workflow_states")
    def test_skips_when_no_matching_state(
        self,
        mock_states: MagicMock,
        mock_update: MagicMock,
        tracker: LinearTracker,
    ) -> None:
        mock_states.return_value = []
        tracker.update_status(issue_id="uuid-1", status=FeatureStatus.IMPLEMENTING)
        mock_update.assert_not_called()


class TestLinkPr:
    def test_noop(self, tracker: LinearTracker) -> None:
        tracker.link_pr(issue_id="uuid-1", pr_url="https://example.com/pr/1")
