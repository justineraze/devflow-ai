"""Tests for devflow.workflow — YAML loading, state persistence, phase management."""

from pathlib import Path

import pytest

from devflow.models import Feature, PhaseStatus, WorkflowState
from devflow.workflow import (
    advance_phase,
    create_feature,
    load_state,
    load_workflow,
    save_state,
)


@pytest.fixture
def workflows_dir(tmp_path: Path) -> Path:
    """Create a temporary workflows directory with a test workflow."""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "standard.yaml").write_text(
        """
name: standard
description: Standard development workflow
phases:
  - name: planning
    agent: planner
    description: Plan the implementation
  - name: implementing
    agent: developer
    description: Write the code
  - name: reviewing
    agent: reviewer
    description: Review the code
  - name: gate
    agent: tester
    description: Run quality gate
"""
    )
    return wf_dir


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path / "project"


class TestLoadWorkflow:
    def test_loads_valid_workflow(self, workflows_dir: Path) -> None:
        wf = load_workflow("standard", workflows_dir)
        assert wf.name == "standard"
        assert len(wf.phases) == 4
        assert wf.phases[0].name == "planning"
        assert wf.phases[0].agent == "planner"

    def test_missing_workflow_raises(self, workflows_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_workflow("nonexistent", workflows_dir)


class TestStatePersistence:
    def test_save_and_load_roundtrip(self, project_dir: Path) -> None:
        state = WorkflowState()
        feat = Feature(id="f-001", description="test feature")
        state.add_feature(feat)

        save_state(state, project_dir)
        loaded = load_state(project_dir)

        assert loaded.get_feature("f-001") is not None
        assert loaded.get_feature("f-001").description == "test feature"

    def test_load_empty_state(self, project_dir: Path) -> None:
        """Loading from a non-existent directory returns empty state."""
        state = load_state(project_dir)
        assert len(state.features) == 0

    def test_crash_safe_write(self, project_dir: Path) -> None:
        """Verify tmp file is used for crash-safe write (no .tmp left behind)."""
        state = WorkflowState()
        save_state(state, project_dir)
        devflow_dir = project_dir / ".devflow"
        assert (devflow_dir / "state.json").exists()
        assert not (devflow_dir / "state.json.tmp").exists()


class TestCreateFeature:
    def test_creates_feature_with_phases(self, workflows_dir: Path) -> None:
        state = WorkflowState()
        feat = create_feature(
            state, "f-001", "test feature", "standard", workflows_dir
        )
        assert feat.id == "f-001"
        assert len(feat.phases) == 4
        assert feat.phases[0].name == "planning"
        assert all(p.status == PhaseStatus.PENDING for p in feat.phases)

    def test_duplicate_feature_raises(self, workflows_dir: Path) -> None:
        state = WorkflowState()
        create_feature(state, "f-001", "first", "standard", workflows_dir)
        with pytest.raises(ValueError, match="already exists"):
            create_feature(state, "f-001", "duplicate", "standard", workflows_dir)


class TestAdvancePhase:
    def test_starts_first_pending_phase(self, workflows_dir: Path) -> None:
        state = WorkflowState()
        feat = create_feature(state, "f-001", "test", "standard", workflows_dir)
        phase = advance_phase(feat)
        assert phase is not None
        assert phase.name == "planning"
        assert phase.status == PhaseStatus.IN_PROGRESS

    def test_skips_completed_phases(self, workflows_dir: Path) -> None:
        state = WorkflowState()
        feat = create_feature(state, "f-001", "test", "standard", workflows_dir)
        feat.phases[0].start()
        feat.phases[0].complete()
        phase = advance_phase(feat)
        assert phase is not None
        assert phase.name == "implementing"

    def test_returns_none_when_all_done(self, workflows_dir: Path) -> None:
        state = WorkflowState()
        feat = create_feature(state, "f-001", "test", "standard", workflows_dir)
        for p in feat.phases:
            p.start()
            p.complete()
        assert advance_phase(feat) is None
