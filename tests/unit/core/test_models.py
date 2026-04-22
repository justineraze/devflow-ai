"""Tests for devflow.core.models — state machine, transitions, and data models."""


import pytest

from devflow.core.models import (
    ComplexityScore,
    Feature,
    FeatureMetadata,
    FeatureStatus,
    InvalidTransition,
    PhaseName,
    PhaseRecord,
    PhaseStatus,
    WorkflowState,
)


class TestComplexityScore:
    def test_total_is_sum_of_dimensions(self) -> None:
        score = ComplexityScore(files_touched=1, integrations=2, security=0, scope=1)
        assert score.total == 4

    def test_all_zeros_gives_total_zero(self) -> None:
        score = ComplexityScore()
        assert score.total == 0

    def test_max_score_is_twelve(self) -> None:
        score = ComplexityScore(files_touched=3, integrations=3, security=3, scope=3)
        assert score.total == 12

    def test_workflow_quick_at_zero(self) -> None:
        score = ComplexityScore()
        assert score.workflow == "quick"

    def test_workflow_quick_at_boundary(self) -> None:
        score = ComplexityScore(files_touched=1, integrations=1, security=0, scope=0)
        assert score.total == 2
        assert score.workflow == "quick"

    def test_workflow_light(self) -> None:
        score = ComplexityScore(files_touched=1, integrations=1, security=1, scope=0)
        assert score.total == 3
        assert score.workflow == "light"

    def test_workflow_light_at_boundary(self) -> None:
        score = ComplexityScore(files_touched=2, integrations=1, security=1, scope=1)
        assert score.total == 5
        assert score.workflow == "light"

    def test_workflow_standard(self) -> None:
        score = ComplexityScore(files_touched=2, integrations=2, security=1, scope=1)
        assert score.total == 6
        assert score.workflow == "standard"

    def test_workflow_standard_at_boundary(self) -> None:
        score = ComplexityScore(files_touched=2, integrations=2, security=2, scope=2)
        assert score.total == 8
        assert score.workflow == "standard"

    def test_workflow_full(self) -> None:
        score = ComplexityScore(files_touched=3, integrations=3, security=2, scope=1)
        assert score.total == 9
        assert score.workflow == "full"

    def test_workflow_full_at_max(self) -> None:
        score = ComplexityScore(files_touched=3, integrations=3, security=3, scope=3)
        assert score.total == 12
        assert score.workflow == "full"

    def test_complexity_stored_in_feature_metadata(self) -> None:
        score = ComplexityScore(files_touched=1, integrations=0, security=0, scope=1)
        meta = FeatureMetadata(complexity=score)
        assert meta.complexity is not None
        assert meta.complexity.workflow == "quick"

    def test_feature_metadata_complexity_defaults_none(self) -> None:
        meta = FeatureMetadata()
        assert meta.complexity is None


class TestPhaseRecord:
    def test_start_sets_status_and_timestamp(self) -> None:
        phase = PhaseRecord(name="planning")
        phase.start()
        assert phase.status == PhaseStatus.IN_PROGRESS
        assert phase.started_at is not None

    def test_complete_sets_status_and_output(self) -> None:
        phase = PhaseRecord(name="planning")
        phase.start()
        phase.complete(output="plan ready")
        assert phase.status == PhaseStatus.DONE
        assert phase.output == "plan ready"
        assert phase.completed_at is not None

    def test_fail_sets_error(self) -> None:
        phase = PhaseRecord(name="planning")
        phase.start()
        phase.fail(error="timeout")
        assert phase.status == PhaseStatus.FAILED
        assert phase.error == "timeout"


class TestFeatureTransitions:
    def test_valid_transition_pending_to_planning(self) -> None:
        feat = Feature(id="f-001", description="test")
        feat.transition_to(FeatureStatus.PLANNING)
        assert feat.status == FeatureStatus.PLANNING

    def test_valid_transition_planning_to_plan_review(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.PLANNING)
        feat.transition_to(FeatureStatus.PLAN_REVIEW)
        assert feat.status == FeatureStatus.PLAN_REVIEW

    def test_valid_transition_implementing_to_reviewing(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.IMPLEMENTING)
        feat.transition_to(FeatureStatus.REVIEWING)
        assert feat.status == FeatureStatus.REVIEWING

    def test_valid_transition_gate_to_done(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.GATE)
        feat.transition_to(FeatureStatus.DONE)
        assert feat.status == FeatureStatus.DONE

    def test_invalid_transition_raises(self) -> None:
        feat = Feature(id="f-001", description="test")
        with pytest.raises(InvalidTransition):
            feat.transition_to(FeatureStatus.DONE)

    def test_cannot_leave_done(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.DONE)
        with pytest.raises(InvalidTransition):
            feat.transition_to(FeatureStatus.IMPLEMENTING)

    def test_failed_can_recover(self) -> None:
        """Failed features can be resumed — transition back to any state."""
        feat = Feature(id="f-001", description="test", status=FeatureStatus.FAILED)
        feat.transition_to(FeatureStatus.PENDING)
        assert feat.status == FeatureStatus.PENDING

    def test_any_state_can_go_to_blocked(self) -> None:
        for status in FeatureStatus:
            if status in {FeatureStatus.DONE, FeatureStatus.FAILED}:
                continue
            feat = Feature(id="f-001", description="test", status=status)
            feat.transition_to(FeatureStatus.BLOCKED)
            assert feat.status == FeatureStatus.BLOCKED

    def test_any_non_terminal_can_fail(self) -> None:
        for status in FeatureStatus:
            if status in {FeatureStatus.DONE, FeatureStatus.FAILED}:
                continue
            feat = Feature(id="f-001", description="test", status=status)
            feat.transition_to(FeatureStatus.FAILED)
            assert feat.status == FeatureStatus.FAILED

    def test_transition_updates_timestamp(self) -> None:
        feat = Feature(id="f-001", description="test")
        before = feat.updated_at
        feat.transition_to(FeatureStatus.PLANNING)
        assert feat.updated_at >= before

    def test_blocked_can_return_to_previous_states(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.BLOCKED)
        feat.transition_to(FeatureStatus.IMPLEMENTING)
        assert feat.status == FeatureStatus.IMPLEMENTING

    def test_pending_to_implementing_for_fix_workflow(self) -> None:
        """Fix workflow skips planning and goes straight to implementing."""
        feat = Feature(id="f-001", description="bug fix")
        feat.transition_to(FeatureStatus.IMPLEMENTING)
        assert feat.status == FeatureStatus.IMPLEMENTING


class TestFeatureProperties:
    def test_current_phase_returns_active(self) -> None:
        phase = PhaseRecord(name="planning")
        phase.start()
        feat = Feature(id="f-001", description="test", phases=[phase])
        assert feat.current_phase is not None
        assert feat.current_phase.name == "planning"

    def test_current_phase_returns_none_when_idle(self) -> None:
        feat = Feature(id="f-001", description="test")
        assert feat.current_phase is None

    def test_is_terminal_done(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.DONE)
        assert feat.is_terminal is True

    def test_failed_is_not_terminal(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.FAILED)
        assert feat.is_terminal is False

    def test_not_terminal_pending(self) -> None:
        feat = Feature(id="f-001", description="test")
        assert feat.is_terminal is False


class TestFeatureFindPhase:
    def _feature_with(self, *names: str) -> Feature:
        return Feature(
            id="f-001",
            description="test",
            phases=[PhaseRecord(name=n) for n in names],
        )

    def test_returns_phase_by_name(self) -> None:
        feat = self._feature_with("planning", "implementing", "gate")
        phase = feat.find_phase("implementing")
        assert phase is not None
        assert phase.name == "implementing"

    def test_returns_none_when_missing(self) -> None:
        feat = self._feature_with("planning")
        assert feat.find_phase("reviewing") is None

    def test_returns_first_match(self) -> None:
        """Duplicate names should not happen in practice, but behaviour is defined."""
        duplicate = Feature(
            id="f-001",
            description="test",
            phases=[
                PhaseRecord(name="fixing", status=PhaseStatus.DONE),
                PhaseRecord(name="fixing"),
            ],
        )
        first = duplicate.find_phase("fixing")
        assert first is not None
        assert first.status == PhaseStatus.DONE

    def test_accepts_phase_name_enum(self) -> None:
        feat = self._feature_with("planning", "gate")
        phase = feat.find_phase(PhaseName.GATE)
        assert phase is not None
        assert phase.name == "gate"

    def test_empty_phases_returns_none(self) -> None:
        feat = Feature(id="f-001", description="test")
        assert feat.find_phase("planning") is None


class TestWorkflowState:
    def test_add_and_get_feature(self) -> None:
        state = WorkflowState()
        feat = Feature(id="f-001", description="test")
        state.add_feature(feat)
        assert state.get_feature("f-001") is feat

    def test_get_missing_feature_returns_none(self) -> None:
        state = WorkflowState()
        assert state.get_feature("nope") is None

    def test_base_branch_defaults_to_main(self) -> None:
        state = WorkflowState()
        assert state.base_branch == "main"

    def test_base_branch_roundtrip(self) -> None:
        state = WorkflowState(base_branch="develop")
        data = state.model_dump()
        loaded = WorkflowState.model_validate(data)
        assert loaded.base_branch == "develop"

    def test_add_feature_updates_timestamp(self) -> None:
        state = WorkflowState()
        before = state.updated_at
        feat = Feature(id="f-001", description="test")
        state.add_feature(feat)
        assert state.updated_at >= before
