"""Tests for ``devflow do`` — task on current branch, no PR."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.metrics import PhaseMetrics
from devflow.core.models import ComplexityScore
from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_do_loop
from devflow.orchestration.lifecycle import start_do

_PHASE_OK = (True, "done", PhaseMetrics())
_PHASE_FAIL = (False, "error", PhaseMetrics())


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# start_do — auto-detect workflow
# ---------------------------------------------------------------------------


class TestStartDo:
    def test_auto_detects_workflow(self, project_dir: Path) -> None:
        """Without explicit workflow, complexity scoring is used."""
        mock_score = ComplexityScore(
            files_touched=2, integrations=1, security=0, scope=1,
        )
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
            return_value=mock_score,
        ) as mock_scorer:
            feature = start_do("Refactor module", base=project_dir)
        mock_scorer.assert_called_once()
        assert feature.workflow == mock_score.workflow

    def test_explicit_workflow_skips_scoring(self, project_dir: Path) -> None:
        """When workflow is provided, scoring is skipped."""
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
        ) as mock_scorer:
            feature = start_do("Add logging", workflow_name="quick", base=project_dir)
        mock_scorer.assert_not_called()
        assert feature.workflow == "quick"

    def test_creates_feature_in_state(self, project_dir: Path) -> None:
        feature = start_do("Add logging", workflow_name="quick", base=project_dir)
        state = load_state(project_dir)
        assert state.get_feature(feature.id) is not None

    def test_quick_workflow_has_two_phases(self, project_dir: Path) -> None:
        feature = start_do("Fix typo", workflow_name="quick", base=project_dir)
        assert len(feature.phases) == 2
        assert feature.phases[0].name == "implementing"
        assert feature.phases[1].name == "gate"


# ---------------------------------------------------------------------------
# execute_do_loop — delegates to execute_build_loop(create_pr=False)
# ---------------------------------------------------------------------------


class TestExecuteDoLoopDelegation:
    """execute_do_loop passes create_pr=False to execute_build_loop."""

    @patch("devflow.orchestration.build.execute_build_loop", return_value=True)
    def test_delegates_with_create_pr_false(
        self, mock_build: MagicMock, project_dir: Path,
    ) -> None:
        feature = start_do("task", workflow_name="quick", base=project_dir)
        result = execute_do_loop(feature, base=project_dir)

        assert result is True
        mock_build.assert_called_once_with(
            feature, base=project_dir, verbose=False, create_pr=False, callbacks=None,
        )


# ---------------------------------------------------------------------------
# execute_build_loop(create_pr=False) — integration-level
# ---------------------------------------------------------------------------


class TestBuildLoopDoMode:
    """Test execute_build_loop with create_pr=False (do mode)."""

    @patch("devflow.integrations.git.get_head_sha", return_value="abc1234def")
    @patch("devflow.integrations.git.commit_changes", return_value=True)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase")
    def test_success_no_branch_no_pr(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        mock_sha: MagicMock,
        project_dir: Path,
    ) -> None:
        mock_exec.side_effect = [_PHASE_OK, _PHASE_OK]  # implementing, gate
        from devflow.orchestration.build import execute_build_loop

        feature = start_do("Add feature X", workflow_name="quick", base=project_dir)
        result = execute_build_loop(feature, base=project_dir, create_pr=False)

        assert result is True

    @patch("devflow.orchestration.build.setup_gate_retry", return_value=False)
    @patch("devflow.integrations.git.get_head_sha")
    @patch("devflow.integrations.git.commit_changes", return_value=True)
    @patch("devflow.integrations.git.get_untracked_files", return_value=[])
    @patch("devflow.orchestration.build._execute_phase")
    def test_failure_keeps_changes_on_branch(
        self,
        mock_exec: MagicMock,
        mock_untracked: MagicMock,
        mock_commit: MagicMock,
        mock_sha: MagicMock,
        mock_gate_retry: MagicMock,
        project_dir: Path,
    ) -> None:
        # Calls: initial SHA save, pre-phase SHA, failure-path SHA check.
        mock_sha.side_effect = ["initial_sha_full", "pre_phase_sha", "changed_sha_full"]
        mock_exec.side_effect = [_PHASE_OK, _PHASE_FAIL]  # implementing ok, gate fail

        from devflow.orchestration.build import execute_build_loop

        feature = start_do("Broken change", workflow_name="quick", base=project_dir)
        result = execute_build_loop(feature, base=project_dir, create_pr=False)

        assert result is False
        # No auto-revert — changes stay on the branch.


# ---------------------------------------------------------------------------
# Quick workflow instructions — unchanged behavior
# ---------------------------------------------------------------------------


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
