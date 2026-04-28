"""Tests for devflow.orchestration.phase_exec.

Covers: run_phase, complete_phase, fail_phase, reset_planning_phases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseRecord,
    PhaseStatus,
    WorkflowState,
)
from devflow.core.workflow import load_state, save_state
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    reset_planning_phases,
    run_phase,
)


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _save_feature(feature: Feature, base: Path) -> None:
    """Persist a single feature to state.json."""
    state = WorkflowState(features={feature.id: feature})
    save_state(state, base)


class TestRunPhase:
    def test_returns_none_for_unknown_feature(self, project_dir: Path) -> None:
        """run_phase with a feature_id not in state returns None."""
        ghost = Feature(id="ghost-001", description="ghost")
        # state.json is absent → empty state → feature not found
        result = run_phase(ghost, project_dir)
        assert result is None

    def test_advances_next_pending_phase(self, project_dir: Path) -> None:
        """First pending phase is started and returned."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PENDING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.PENDING)],
        )
        _save_feature(feature, project_dir)

        phase = run_phase(feature, project_dir)

        assert phase is not None
        assert phase.name == "planning"
        assert phase.status == PhaseStatus.IN_PROGRESS
        assert phase.started_at is not None

    def test_transitions_feature_status(self, project_dir: Path) -> None:
        """Feature transitions to the status matching the started phase."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PENDING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.PENDING)],
        )
        _save_feature(feature, project_dir)

        run_phase(feature, project_dir)

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.PLANNING

    def test_walks_to_done_when_no_pending_phase(self, project_dir: Path) -> None:
        """When all phases are done, feature transitions to DONE and returns None."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.GATE,
            phases=[PhaseRecord(name="gate", status=PhaseStatus.DONE)],
        )
        _save_feature(feature, project_dir)

        result = run_phase(feature, project_dir)

        assert result is None
        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.DONE

    def test_no_transition_when_target_matches(self, project_dir: Path) -> None:
        """No error when feature status already equals the phase's target status."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PLANNING,  # already at target
            phases=[PhaseRecord(name="planning", status=PhaseStatus.PENDING)],
        )
        _save_feature(feature, project_dir)

        phase = run_phase(feature, project_dir)

        assert phase is not None
        assert phase.name == "planning"
        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.PLANNING


class TestCompletePhase:
    def test_persists_output_as_artifact(self, project_dir: Path) -> None:
        """Output is written to .devflow/<id>/planning.md and cleared in state."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PLANNING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.IN_PROGRESS)],
        )
        _save_feature(feature, project_dir)

        complete_phase("feat-001", "planning", output="## Plan\nstep 1", base=project_dir)

        artifact = project_dir / ".devflow" / "feat-001" / "planning.md"
        assert artifact.exists()
        assert "## Plan" in artifact.read_text()

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        phase = reloaded.find_phase("planning")
        assert phase is not None
        assert phase.output == ""  # cleared after artifact write

    def test_no_artifact_when_output_empty(self, project_dir: Path) -> None:
        """Empty output produces no artifact file."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PLANNING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.IN_PROGRESS)],
        )
        _save_feature(feature, project_dir)

        complete_phase("feat-001", "planning", output="", base=project_dir)

        artifact = project_dir / ".devflow" / "feat-001" / "planning.md"
        assert not artifact.exists()

    def test_noop_on_unknown_feature(self, project_dir: Path) -> None:
        """No crash when feature_id is not in state."""
        complete_phase("ghost-001", "planning", output="x", base=project_dir)

    def test_ignores_non_in_progress_phase(self, project_dir: Path) -> None:
        """A DONE phase is not modified and no artifact is written."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.PLANNING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.DONE)],
        )
        _save_feature(feature, project_dir)

        complete_phase("feat-001", "planning", output="should be ignored", base=project_dir)

        artifact = project_dir / ".devflow" / "feat-001" / "planning.md"
        assert not artifact.exists()


class TestFailPhase:
    def test_marks_phase_failed_and_feature_failed(self, project_dir: Path) -> None:
        """IN_PROGRESS phase → FAILED; feature status → FAILED."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.IMPLEMENTING,
            phases=[PhaseRecord(name="implementing", status=PhaseStatus.IN_PROGRESS)],
        )
        _save_feature(feature, project_dir)

        fail_phase("feat-001", "implementing", error="timeout", base=project_dir)

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        phase = reloaded.find_phase("implementing")
        assert phase is not None
        assert phase.status == PhaseStatus.FAILED
        assert phase.error == "timeout"
        assert reloaded.status == FeatureStatus.FAILED

    def test_still_transitions_feature_when_phase_missing(self, project_dir: Path) -> None:
        """Feature transitions to FAILED even when the named phase is absent."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.IMPLEMENTING,
            phases=[PhaseRecord(name="implementing", status=PhaseStatus.IN_PROGRESS)],
        )
        _save_feature(feature, project_dir)

        # "gate" phase does not exist on this feature
        fail_phase("feat-001", "gate", error="boom", base=project_dir)

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.FAILED

    def test_noop_on_unknown_feature(self, project_dir: Path) -> None:
        """No crash when feature_id is not in state."""
        fail_phase("ghost-001", "planning", error="x", base=project_dir)


class TestResetPlanningPhases:
    def test_resets_architecture_planning_plan_review(self, project_dir: Path) -> None:
        """DONE planning phases are reset to PENDING; other phases are untouched."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.IMPLEMENTING,
            phases=[
                PhaseRecord(name="planning", status=PhaseStatus.DONE, output="old"),
                PhaseRecord(name="implementing", status=PhaseStatus.DONE),
            ],
        )
        _save_feature(feature, project_dir)

        reset_planning_phases("feat-001", project_dir)

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        planning = reloaded.find_phase("planning")
        assert planning is not None
        assert planning.status == PhaseStatus.PENDING
        assert planning.output == ""
        assert planning.started_at is None
        assert planning.completed_at is None

        implementing = reloaded.find_phase("implementing")
        assert implementing is not None
        assert implementing.status == PhaseStatus.DONE  # untouched

    def test_sets_feature_status_to_pending(self, project_dir: Path) -> None:
        """Feature status is forced to PENDING regardless of previous status."""
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.IMPLEMENTING,
            phases=[PhaseRecord(name="planning", status=PhaseStatus.DONE)],
        )
        _save_feature(feature, project_dir)

        reset_planning_phases("feat-001", project_dir)

        reloaded = load_state(project_dir).get_feature("feat-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.PENDING

    def test_noop_on_unknown_feature(self, project_dir: Path) -> None:
        """No crash when feature_id is not in state."""
        reset_planning_phases("ghost-001", project_dir)
