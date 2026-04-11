"""Tests for devflow.build — orchestration logic."""

from pathlib import Path

import pytest

from devflow.build import (
    _generate_feature_id,
    complete_phase,
    fail_phase,
    resume_build,
    run_phase,
    start_build,
    start_fix,
)
from devflow.models import FeatureStatus, PhaseStatus
from devflow.workflow import load_state, save_state


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project directory with workflows."""
    return tmp_path


@pytest.fixture
def workflows_dir() -> Path:
    """Return the real workflows directory."""
    return Path(__file__).resolve().parent.parent / "workflows"


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
        assert feature is not None
        assert feature.description == "Add dark mode"
        assert feature.workflow == "standard"

        # Verify persisted.
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

    def test_returns_none_for_terminal(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        # Force to done state.
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        tracked.status = FeatureStatus.DONE
        save_state(state, project_dir)
        assert resume_build(feature.id, project_dir) is None


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
        result = run_phase(feature, project_dir)
        assert result is None


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
