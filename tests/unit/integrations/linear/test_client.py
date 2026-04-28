"""Tests for the Linear GraphQL client (mocked — no real API calls)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.integrations.linear.client import (
    LinearError,
    create_issue,
    get_teams,
    get_workflow_states,
    is_configured,
    update_issue_state,
)


class TestIsConfigured:
    def test_true_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test123")
        assert is_configured() is True

    def test_false_when_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        assert is_configured() is False

    def test_true_when_key_file_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        key_dir = tmp_path / ".devflow"
        key_dir.mkdir()
        (key_dir / "linear.key").write_text("lin_api_from_file\n")
        assert is_configured() is True

    def test_env_takes_precedence_over_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "from_env")
        monkeypatch.chdir(tmp_path)
        key_dir = tmp_path / ".devflow"
        key_dir.mkdir()
        (key_dir / "linear.key").write_text("from_file")

        from devflow.integrations.linear.client import _api_key

        assert _api_key() == "from_env"


def _mock_urlopen(response_data: dict) -> MagicMock:
    """Build a mock for urllib.request.urlopen returning *response_data*."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"data": response_data}).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestGetTeams:
    @patch("devflow.integrations.linear.client.urllib.request.urlopen")
    def test_returns_teams(
        self, mock_open: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_open.return_value = _mock_urlopen({
            "teams": {"nodes": [
                {"id": "t1", "key": "ABC", "name": "Team Alpha"},
            ]},
        })
        teams = get_teams()
        assert len(teams) == 1
        assert teams[0]["key"] == "ABC"


class TestCreateIssue:
    @patch("devflow.integrations.linear.client.urllib.request.urlopen")
    def test_creates_and_returns_issue(
        self, mock_open: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_open.return_value = _mock_urlopen({
            "issueCreate": {"issue": {
                "id": "uuid-1", "identifier": "ABC-42",
                "title": "test", "url": "https://linear.app/abc/issue/ABC-42",
            }},
        })
        issue = create_issue("team-1", "test issue")
        assert issue["identifier"] == "ABC-42"

    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        with pytest.raises(LinearError, match="LINEAR_API_KEY"):
            create_issue("team-1", "test")


class TestUpdateIssueState:
    @patch("devflow.integrations.linear.client.urllib.request.urlopen")
    def test_updates_state(
        self, mock_open: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_open.return_value = _mock_urlopen({
            "issueUpdate": {"issue": {
                "id": "uuid-1", "identifier": "ABC-42",
                "state": {"name": "In Progress"},
            }},
        })
        result = update_issue_state("uuid-1", "state-started")
        assert result["state"]["name"] == "In Progress"


class TestGetWorkflowStates:
    @patch("devflow.integrations.linear.client.urllib.request.urlopen")
    def test_returns_states(
        self, mock_open: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_open.return_value = _mock_urlopen({
            "workflowStates": {"nodes": [
                {"id": "s1", "name": "Todo", "type": "unstarted"},
                {"id": "s2", "name": "In Progress", "type": "started"},
                {"id": "s3", "name": "Done", "type": "completed"},
            ]},
        })
        states = get_workflow_states("team-1")
        assert len(states) == 3
        assert states[2]["type"] == "completed"
