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
        """Repeated loads with unchanged mtime return the cached instance."""
        from devflow.core.workflow import clear_workflow_cache

        clear_workflow_cache()
        wf1 = load_workflow("standard", workflows_dir)
        wf2 = load_workflow("standard", workflows_dir)
        assert wf2 is wf1

    def test_mtime_change_invalidates_cache(self, workflows_dir: Path) -> None:
        """Editing a workflow YAML invalidates the cached entry on next load."""
        import os
        import time

        from devflow.core.workflow import clear_workflow_cache

        clear_workflow_cache()
        wf1 = load_workflow("standard", workflows_dir)

        # Touch the file with a forward-dated mtime so the cache treats it
        # as modified even on filesystems with coarse timestamps.
        path = workflows_dir / "standard.yaml"
        future = time.time() + 5
        os.utime(path, (future, future))

        wf2 = load_workflow("standard", workflows_dir)
        assert wf2 is not wf1

    def test_clear_cache_forces_reload(self, workflows_dir: Path) -> None:
        from devflow.core.workflow import clear_workflow_cache

        clear_workflow_cache()
        wf1 = load_workflow("standard", workflows_dir)
        clear_workflow_cache()
        wf2 = load_workflow("standard", workflows_dir)
        assert wf2 is not wf1


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


class TestStateLock:
    """File-lock semantics around .devflow/state.lock (POSIX-only)."""

    def test_mutate_feature_persists_changes(self, project_dir: Path) -> None:
        from devflow.core.models import Feature, FeatureStatus
        from devflow.core.workflow import load_state, mutate_feature, save_state

        state = load_state(project_dir)
        feature = Feature(
            id="feat-lock-001",
            description="test locking",
            status=FeatureStatus.PENDING,
            phases=[],
        )
        state.add_feature(feature)
        save_state(state, project_dir)

        with mutate_feature("feat-lock-001", project_dir) as feat:
            assert feat is not None
            feat.description = "updated"

        reloaded = load_state(project_dir)
        assert reloaded.get_feature("feat-lock-001").description == "updated"

    def test_lock_file_is_created(self, project_dir: Path) -> None:
        from devflow.core.workflow import _state_lock

        with _state_lock(project_dir):
            lock_path = project_dir / ".devflow" / "state.lock"
            assert lock_path.exists()
