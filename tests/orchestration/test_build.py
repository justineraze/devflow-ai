"""Tests for devflow.orchestration.build — orchestration logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.models import FeatureStatus, PhaseStatus
from devflow.core.workflow import load_state, save_state
from devflow.orchestration.build import (
    _generate_feature_id,
    _get_phase_agent,
    complete_phase,
    execute_build_loop,
    fail_phase,
    resume_build,
    retry_build,
    run_phase,
    start_build,
    start_fix,
)
from devflow.orchestration.stream import PhaseMetrics

_PHASE_OK = (True, "done", PhaseMetrics())


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestGenerateFeatureId:
    def test_generates_slug_from_description(self) -> None:
        fid = _generate_feature_id("Add user authentication")
        assert fid.startswith("feat-add-user-authentication-")

    def test_handles_empty_description(self) -> None:
        fid = _generate_feature_id("")
        assert fid.startswith("feat-")

    def test_strips_special_characters(self) -> None:
        fid = _generate_feature_id("Fix bug #123 — urgent!")
        assert "#" not in fid
        assert "!" not in fid


class TestStartBuild:
    def test_creates_feature_in_state(self, project_dir: Path) -> None:
        feature = start_build("Add dark mode", "standard", project_dir)
        assert feature.description == "Add dark mode"
        assert feature.workflow == "standard"
        state = load_state(project_dir)
        assert state.get_feature(feature.id) is not None

    def test_avoids_id_collision(self, project_dir: Path) -> None:
        f1 = start_build("test feature", "standard", project_dir)
        f2 = start_build("test feature", "standard", project_dir)
        assert f1.id != f2.id

    def test_creates_phases_from_workflow(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert len(feature.phases) == 4
        assert feature.phases[0].name == "planning"


class TestStartFix:
    def test_uses_quick_workflow(self, project_dir: Path) -> None:
        feature = start_fix("Fix broken login", project_dir)
        assert feature.workflow == "quick"
        assert len(feature.phases) == 2
        assert feature.phases[0].name == "implementing"


class TestResumeBuild:
    def test_resumes_existing_feature(self, project_dir: Path) -> None:
        original = start_build("test", "standard", project_dir)
        resumed = resume_build(original.id, project_dir)
        assert resumed is not None
        assert resumed.id == original.id

    def test_returns_none_for_missing(self, project_dir: Path) -> None:
        assert resume_build("nonexistent", project_dir) is None

    def test_returns_none_for_done(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        tracked.status = FeatureStatus.DONE
        save_state(state, project_dir)
        assert resume_build(feature.id, project_dir) is None

    def test_recovers_failed_feature(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        # Advance to implementing, then fail it.
        run_phase(feature, project_dir)  # planning
        complete_phase(feature.id, "planning", "plan", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        run_phase(tracked, project_dir)  # implementing
        fail_phase(feature.id, "implementing", "broke", project_dir)

        # Resume should recover.
        resumed = resume_build(feature.id, project_dir)
        assert resumed is not None
        assert resumed.status != FeatureStatus.FAILED

        # The failed phase should be pending again.
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        impl_phase = next(p for p in tracked.phases if p.name == "implementing")
        assert impl_phase.status == PhaseStatus.PENDING


class TestRetryBuild:
    def test_retries_failed_feature(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        # Advance to implementing, then fail it.
        run_phase(feature, project_dir)  # planning
        complete_phase(feature.id, "planning", "plan", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        run_phase(tracked, project_dir)  # implementing
        fail_phase(feature.id, "implementing", "broke", project_dir)

        retried = retry_build(feature.id, project_dir)
        assert retried is not None
        assert retried.status != FeatureStatus.FAILED

        # The failed phase should be pending again.
        impl_phase = next(p for p in retried.phases if p.name == "implementing")
        assert impl_phase.status == PhaseStatus.PENDING

    def test_returns_none_for_non_failed(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert retry_build(feature.id, project_dir) is None

    def test_returns_none_for_unknown(self, project_dir: Path) -> None:
        assert retry_build("nonexistent", project_dir) is None


class TestRunPhase:
    def test_advances_to_first_phase(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        phase = run_phase(feature, project_dir)
        assert phase is not None
        assert phase.name == "planning"
        assert phase.status == PhaseStatus.IN_PROGRESS

    def test_returns_none_when_all_done(self, project_dir: Path) -> None:
        feature = start_build("test", "quick", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        for p in tracked.phases:
            p.start()
            p.complete()
        save_state(state, project_dir)
        assert run_phase(feature, project_dir) is None


class TestCompletePhase:
    def test_marks_phase_done(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        run_phase(feature, project_dir)
        complete_phase(feature.id, "planning", "plan complete", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.phases[0].status == PhaseStatus.DONE
        assert tracked.phases[0].output == "plan complete"


class TestFailPhase:
    def test_marks_phase_and_feature_failed(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        run_phase(feature, project_dir)
        fail_phase(feature.id, "planning", "timeout", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.phases[0].status == PhaseStatus.FAILED
        assert tracked.status == FeatureStatus.FAILED


class TestGetPhaseAgent:
    def test_returns_developer_python_for_python_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        state = load_state(project_dir)
        state.stack = "python"
        save_state(state, project_dir)
        assert _get_phase_agent(feature, "implementing", project_dir) == "developer-python"

    def test_returns_developer_typescript_for_ts_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        state = load_state(project_dir)
        state.stack = "typescript"
        save_state(state, project_dir)
        assert _get_phase_agent(feature, "implementing", project_dir) == "developer-typescript"

    def test_returns_developer_when_no_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert _get_phase_agent(feature, "implementing", project_dir) == "developer"

    def test_non_developer_agent_unchanged_with_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        state = load_state(project_dir)
        state.stack = "python"
        save_state(state, project_dir)
        assert _get_phase_agent(feature, "planning", project_dir) == "planner"


class TestAutoCommitAfterPhase:
    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_diff_stat", return_value="")
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_OK)
    @patch("devflow.integrations.git.create_branch", return_value="feat/test")
    @patch("devflow.integrations.git.push_and_create_pr", return_value="https://github.com/pr/1")
    def test_commit_called_after_implementing(
        self, mock_pr: MagicMock, mock_branch: MagicMock,
        mock_exec: MagicMock, mock_diff: MagicMock, mock_commit: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_build("test", "quick", project_dir)
        execute_build_loop(feature, base=project_dir)
        # commit_changes should be called with a message containing "implementing".
        commit_msgs = [c[0][0] for c in mock_commit.call_args_list]
        assert any("implementing" in msg for msg in commit_msgs)

    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_diff_stat", return_value="")
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_OK)
    @patch("devflow.integrations.git.create_branch", return_value="feat/test")
    @patch("devflow.integrations.git.push_and_create_pr", return_value="https://github.com/pr/1")
    def test_commit_not_called_for_gate(
        self, mock_pr: MagicMock, mock_branch: MagicMock,
        mock_exec: MagicMock, mock_diff: MagicMock, mock_commit: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_build("test", "quick", project_dir)
        execute_build_loop(feature, base=project_dir)
        commit_msgs = [c[0][0] for c in mock_commit.call_args_list]
        assert not any("gate" in msg for msg in commit_msgs)
