"""Tests for devflow.models — state machine, transitions, and data models."""


import pytest

from devflow.models import (
    Feature,
    FeatureStatus,
    InvalidTransition,
    PhaseRecord,
    PhaseStatus,
    WorkflowState,
)


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

    def test_cannot_leave_failed(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.FAILED)
        with pytest.raises(InvalidTransition):
            feat.transition_to(FeatureStatus.PENDING)

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

    def test_is_terminal_failed(self) -> None:
        feat = Feature(id="f-001", description="test", status=FeatureStatus.FAILED)
        assert feat.is_terminal is True

    def test_not_terminal_pending(self) -> None:
        feat = Feature(id="f-001", description="test")
        assert feat.is_terminal is False


class TestWorkflowState:
    def test_add_and_get_feature(self) -> None:
        state = WorkflowState()
        feat = Feature(id="f-001", description="test")
        state.add_feature(feat)
        assert state.get_feature("f-001") is feat

    def test_get_missing_feature_returns_none(self) -> None:
        state = WorkflowState()
        assert state.get_feature("nope") is None

    def test_add_feature_updates_timestamp(self) -> None:
        state = WorkflowState()
        before = state.updated_at
        feat = Feature(id="f-001", description="test")
        state.add_feature(feat)
        assert state.updated_at >= before
