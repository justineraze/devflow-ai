"""Tests for Linear sync logic (mocked API)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.models import Feature, FeatureStatus, WorkflowState
from devflow.core.workflow import load_state, save_state
from devflow.integrations.linear.sync import (
    SyncResult,
    create_issue_for_feature,
    sync_all,
    sync_feature_to_linear,
    sync_single_feature,
)


def _set_linear_team(project_dir: Path, team: str) -> None:
    """Write a config.yaml with the given Linear team."""
    from devflow.core.config import DevflowConfig, LinearConfig, save_config
    save_config(DevflowConfig(linear=LinearConfig(team=team)), project_dir)


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestSyncResult:
    def test_total(self) -> None:
        r = SyncResult()
        r.created = ["a", "b"]
        r.updated = ["c"]
        r.skipped = 1
        assert r.total == 4


class TestSyncAllGuards:
    def test_fails_without_api_key(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        result = sync_all(base=project_dir)
        assert len(result.errors) == 1
        assert "LINEAR_API_KEY" in result.errors[0]

    def test_fails_without_team_id(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        state = WorkflowState()
        save_state(state, project_dir)

        result = sync_all(base=project_dir)
        assert len(result.errors) == 1
        assert "linear team" in result.errors[0].lower()


_MOCK_STATES = [
    {"id": "s1", "name": "Backlog", "type": "backlog"},
    {"id": "s2", "name": "Todo", "type": "unstarted"},
    {"id": "s3", "name": "In Progress", "type": "started"},
    {"id": "s4", "name": "Done", "type": "completed"},
]


class TestSyncAllCreates:
    @patch("devflow.integrations.linear.sync.get_workflow_states", return_value=_MOCK_STATES)
    @patch("devflow.integrations.linear.sync.update_issue_state")
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_creates_issues_for_new_features(
        self,
        mock_create: MagicMock,
        mock_update: MagicMock,
        mock_states: MagicMock,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_create.return_value = {"id": "uuid-1", "identifier": "ABC-1"}
        _set_linear_team(project_dir, "team-1")

        state = WorkflowState()
        feat = Feature(
            id="feat-001", description="test feature",
            status=FeatureStatus.IMPLEMENTING, phases=[],
        )
        state.add_feature(feat)
        save_state(state, project_dir)

        result = sync_all(base=project_dir)
        assert "feat-001" in result.created
        assert len(result.errors) == 0

        # Verify UUID stored in linear_issue_id, identifier in linear_issue_key.
        reloaded = load_state(project_dir)
        f = reloaded.get_feature("feat-001")
        assert f.metadata.linear_issue_id == "uuid-1"
        assert f.metadata.linear_issue_key == "ABC-1"

    @patch("devflow.integrations.linear.sync.get_workflow_states", return_value=_MOCK_STATES)
    @patch("devflow.integrations.linear.sync.update_issue_state")
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_skips_archived_features(
        self,
        mock_create: MagicMock,
        mock_update: MagicMock,
        mock_states: MagicMock,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")

        _set_linear_team(project_dir, "team-1")
        state = WorkflowState()
        feat = Feature(
            id="feat-archived", description="old",
            status=FeatureStatus.DONE, phases=[],
        )
        feat.metadata.archived = True
        state.add_feature(feat)
        save_state(state, project_dir)

        result = sync_all(base=project_dir)
        assert result.skipped == 1
        mock_create.assert_not_called()


class TestSyncAllUpdates:
    @patch("devflow.integrations.linear.sync.get_workflow_states", return_value=_MOCK_STATES)
    @patch("devflow.integrations.linear.sync.update_issue_state")
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_updates_existing_issues(
        self,
        mock_create: MagicMock,
        mock_update: MagicMock,
        mock_states: MagicMock,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")

        _set_linear_team(project_dir, "team-1")
        state = WorkflowState()
        feat = Feature(
            id="feat-002", description="existing",
            status=FeatureStatus.DONE, phases=[],
        )
        feat.metadata.linear_issue_id = "uuid-existing"
        state.add_feature(feat)
        save_state(state, project_dir)

        result = sync_all(base=project_dir)
        assert "feat-002" in result.updated
        mock_create.assert_not_called()
        mock_update.assert_called_once_with("uuid-existing", "s4")  # "completed" state


class TestSyncAllErrorHandling:
    @patch("devflow.integrations.linear.sync.get_workflow_states", return_value=_MOCK_STATES)
    @patch("devflow.integrations.linear.sync.update_issue_state")
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_linear_error_captured_not_raised(
        self,
        mock_create: MagicMock,
        mock_update: MagicMock,
        mock_states: MagicMock,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LinearError on one feature should not crash sync for others."""
        from devflow.integrations.linear.client import LinearError

        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        mock_create.side_effect = [
            LinearError("API down"),
            {"id": "uuid-2", "identifier": "ABC-2"},
        ]

        _set_linear_team(project_dir, "team-1")
        state = WorkflowState()
        for fid in ("feat-a", "feat-b"):
            feat = Feature(
                id=fid, description=fid,
                status=FeatureStatus.IMPLEMENTING, phases=[],
            )
            state.add_feature(feat)
        save_state(state, project_dir)

        result = sync_all(base=project_dir)
        assert len(result.errors) == 1
        assert "feat-a" in result.errors[0]
        assert "feat-b" in result.created


class TestSyncFeatureToLinear:
    def test_state_id_none_skips_update(self) -> None:
        """When _resolve_state_id returns None, update is skipped (no crash)."""
        feat = Feature(
            id="feat-x", description="x",
            status=FeatureStatus.IMPLEMENTING, phases=[],
        )
        feat.metadata.linear_issue_id = "uuid-x"
        # Empty state_cache → _resolve_state_id will need API call.
        # Provide a cache with no matching type.
        state_cache: dict[str, dict[str, str]] = {"team-1": {}}
        result = sync_feature_to_linear(feat, "team-1", state_cache)
        assert result is None


class TestCreateIssueForFeature:
    @patch("devflow.integrations.linear.sync.is_configured", return_value=True)
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_returns_identifier(
        self, mock_create: MagicMock, mock_cfg: MagicMock,
    ) -> None:
        mock_create.return_value = {"id": "uuid-new", "identifier": "ABC-99"}
        feat = Feature(
            id="feat-new", description="new feature",
            status=FeatureStatus.PENDING, phases=[],
        )
        key = create_issue_for_feature(feat, "team-1")
        assert key == "ABC-99"
        assert feat.metadata.linear_issue_id == "uuid-new"
        assert feat.metadata.linear_issue_key == "ABC-99"

    @patch("devflow.integrations.linear.sync.is_configured", return_value=False)
    def test_returns_none_when_not_configured(self, mock_cfg: MagicMock) -> None:
        feat = Feature(
            id="feat-nc", description="no config",
            status=FeatureStatus.PENDING, phases=[],
        )
        assert create_issue_for_feature(feat, "team-1") is None

    @patch("devflow.integrations.linear.sync.is_configured", return_value=True)
    @patch("devflow.integrations.linear.sync.create_issue")
    def test_catches_linear_error(
        self, mock_create: MagicMock, mock_cfg: MagicMock,
    ) -> None:
        from devflow.integrations.linear.client import LinearError

        mock_create.side_effect = LinearError("boom")
        feat = Feature(
            id="feat-err", description="error",
            status=FeatureStatus.PENDING, phases=[],
        )
        assert create_issue_for_feature(feat, "team-1") is None
        assert feat.metadata.linear_issue_id is None


class TestSyncSingleFeature:
    @patch("devflow.integrations.linear.sync.is_configured", return_value=True)
    @patch("devflow.integrations.linear.sync.sync_feature_to_linear")
    def test_syncs_when_configured(
        self, mock_sync: MagicMock, mock_cfg: MagicMock,
    ) -> None:
        feat = Feature(
            id="feat-s", description="sync me",
            status=FeatureStatus.DONE, phases=[],
        )
        feat.metadata.linear_issue_id = "uuid-s"
        sync_single_feature(feat, "team-1")
        mock_sync.assert_called_once()

    @patch("devflow.integrations.linear.sync.is_configured", return_value=False)
    def test_noop_when_not_configured(self, mock_cfg: MagicMock) -> None:
        feat = Feature(
            id="feat-nc", description="no",
            status=FeatureStatus.DONE, phases=[],
        )
        feat.metadata.linear_issue_id = "uuid-nc"
        # Should not raise.
        sync_single_feature(feat, "team-1")

    @patch("devflow.integrations.linear.sync.is_configured", return_value=True)
    @patch("devflow.integrations.linear.sync.sync_feature_to_linear")
    def test_noop_when_no_linear_id(
        self, mock_sync: MagicMock, mock_cfg: MagicMock,
    ) -> None:
        feat = Feature(
            id="feat-no", description="no id",
            status=FeatureStatus.DONE, phases=[],
        )
        sync_single_feature(feat, "team-1")
        mock_sync.assert_not_called()

    @patch("devflow.integrations.linear.sync.is_configured", return_value=True)
    @patch("devflow.integrations.linear.sync.sync_feature_to_linear")
    def test_catches_linear_error(
        self, mock_sync: MagicMock, mock_cfg: MagicMock,
    ) -> None:
        from devflow.integrations.linear.client import LinearError

        mock_sync.side_effect = LinearError("network")
        feat = Feature(
            id="feat-e", description="err",
            status=FeatureStatus.DONE, phases=[],
        )
        feat.metadata.linear_issue_id = "uuid-e"
        # Should not raise.
        sync_single_feature(feat, "team-1")
