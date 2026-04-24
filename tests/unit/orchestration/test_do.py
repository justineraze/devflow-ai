"""Tests for the ``devflow do`` command — quick task on current branch."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_do_loop
from devflow.orchestration.lifecycle import start_do
from devflow.orchestration.stream import PhaseMetrics

_PHASE_OK = (True, "done", PhaseMetrics())
_PHASE_FAIL = (False, "error", PhaseMetrics())


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestStartDo:
    def test_uses_quick_workflow(self, project_dir: Path) -> None:
        feature = start_do("Fix typo in README", project_dir)
        assert feature.workflow == "quick"
        assert len(feature.phases) == 2
        assert feature.phases[0].name == "implementing"
        assert feature.phases[1].name == "gate"

    def test_creates_feature_in_state(self, project_dir: Path) -> None:
        feature = start_do("Add logging", project_dir)
        state = load_state(project_dir)
        assert state.get_feature(feature.id) is not None


class TestExecuteDoLoopSuccess:
    """Gate passes on first try — commit stays, SHA printed."""

    @patch("devflow.integrations.git.get_head_sha", return_value="abc1234")
    @patch("devflow.integrations.git.commit_changes", return_value=True)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase")
    def test_success_flow(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        mock_sha: MagicMock,
        project_dir: Path,
    ) -> None:
        mock_exec.side_effect = [_PHASE_OK, _PHASE_OK]  # implementing, gate

        feature = start_do("Add feature X", project_dir)
        result = execute_do_loop(feature, base=project_dir)

        assert result is True
        mock_commit.assert_called_once()
        mock_sha.assert_called_once()


class TestExecuteDoLoopGateFailRevert:
    """Gate fails after retries — commit is reverted."""

    @patch("devflow.integrations.git.revert_head", return_value=True)
    @patch("devflow.integrations.git.get_head_sha", return_value="bad1234")
    @patch("devflow.integrations.git.commit_changes", return_value=True)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase")
    def test_revert_after_gate_failures(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        mock_sha: MagicMock,
        mock_revert: MagicMock,
        project_dir: Path,
    ) -> None:
        # implementing OK, then gate fails 3 times with fixing in between.
        mock_exec.side_effect = [
            _PHASE_OK,   # implementing
            _PHASE_FAIL, # gate attempt 1
            _PHASE_OK,   # fixing 1
            _PHASE_FAIL, # gate attempt 2
            _PHASE_OK,   # fixing 2
            _PHASE_FAIL, # gate attempt 3
        ]

        feature = start_do("Broken change", project_dir)
        result = execute_do_loop(feature, base=project_dir)

        assert result is False
        mock_revert.assert_called_once()


class TestExecuteDoLoopImplementingFails:
    """Implementing phase fails — no commit, no revert."""

    @patch("devflow.integrations.git.revert_head", return_value=True)
    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_FAIL)
    def test_implementing_fail_no_revert(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        mock_revert: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_do("Bad task", project_dir)
        result = execute_do_loop(feature, base=project_dir)

        assert result is False
        mock_commit.assert_not_called()
        mock_revert.assert_not_called()


class TestExecuteDoLoopNoChanges:
    """Implementing succeeds but nothing to commit."""

    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_OK)
    def test_no_changes_is_success(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_do("No-op task", project_dir)
        result = execute_do_loop(feature, base=project_dir)

        assert result is True


class TestQuickInstructions:
    """Quick workflow uses no-commit implementing instructions."""

    def test_quick_workflow_no_commit_instructions(self) -> None:
        from devflow.orchestration.runner import _get_phase_instructions

        instructions = _get_phase_instructions("implementing", workflow="quick")
        assert "Do NOT commit" in instructions
        assert "Do NOT run git add" in instructions

    def test_standard_workflow_keeps_atomic_commits(self) -> None:
        from devflow.orchestration.runner import _get_phase_instructions

        instructions = _get_phase_instructions("implementing", workflow="standard")
        assert "Commits atomiques" in instructions

    def test_non_implementing_unaffected(self) -> None:
        from devflow.orchestration.runner import _get_phase_instructions

        instructions = _get_phase_instructions("fixing", workflow="quick")
        assert "Address the review feedback" in instructions
