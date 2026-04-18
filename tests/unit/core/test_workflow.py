"""Tests for devflow.core.workflow — YAML loading, state persistence, phase management."""

from pathlib import Path

import pytest

from devflow.core.models import Feature, FeatureStatus, PhaseStatus, WorkflowState
from devflow.core.workflow import (
    advance_phase,
    create_feature,
    load_state,
    load_workflow,
    mutate_feature,
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


class TestWorkflowCache:
    def test_same_object_returned_on_second_call(self, workflows_dir: Path) -> None:
        """Default-dir loads are cached — same object returned on repeated calls."""
        from devflow.core import workflow as wf_mod

        # Pre-populate the cache with a known workflow dir.
        wf1 = load_workflow("standard", workflows_dir)
        # Manually seed the cache as if the default dir had been used.
        wf_mod._workflow_cache["standard"] = wf1

        wf2 = load_workflow("standard")
        assert wf2 is wf1

        # Cleanup to avoid polluting other tests.
        wf_mod._workflow_cache.pop("standard", None)

    def test_explicit_dir_bypasses_cache(self, workflows_dir: Path) -> None:
        from devflow.core import workflow as wf_mod

        wf_mod._workflow_cache["standard"] = load_workflow("standard", workflows_dir)
        wf_fresh = load_workflow("standard", workflows_dir)
        assert wf_fresh is not wf_mod._workflow_cache["standard"]
        wf_mod._workflow_cache.pop("standard", None)


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


class TestMutateFeature:
    """mutate_feature yields the feature and auto-saves on exit."""

    def _seed(self, project_dir: Path) -> None:
        state = WorkflowState()
        state.add_feature(Feature(id="f-001", description="seed"))
        save_state(state, project_dir)

    def test_mutation_is_persisted(self, project_dir: Path) -> None:
        self._seed(project_dir)

        with mutate_feature("f-001", project_dir) as feature:
            assert feature is not None
            feature.description = "mutated"

        reloaded = load_state(project_dir).get_feature("f-001")
        assert reloaded is not None
        assert reloaded.description == "mutated"

    def test_status_transition_is_persisted(self, project_dir: Path) -> None:
        self._seed(project_dir)

        with mutate_feature("f-001", project_dir) as feature:
            assert feature is not None
            feature.transition_to(FeatureStatus.PLANNING)

        reloaded = load_state(project_dir).get_feature("f-001")
        assert reloaded is not None
        assert reloaded.status == FeatureStatus.PLANNING

    def test_yields_none_when_feature_missing(self, project_dir: Path) -> None:
        self._seed(project_dir)
        with mutate_feature("missing-id", project_dir) as feature:
            assert feature is None

    def test_no_save_when_feature_missing(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Save is skipped when the feature does not exist — semantics preserved."""
        self._seed(project_dir)
        calls: list[object] = []

        import devflow.core.workflow as wf_mod

        original = wf_mod.save_state

        def tracking(state: WorkflowState, base: Path | None = None) -> Path:
            calls.append(state)
            return original(state, base)

        monkeypatch.setattr(wf_mod, "save_state", tracking)

        with mutate_feature("missing-id", project_dir) as feature:
            assert feature is None

        assert calls == []
