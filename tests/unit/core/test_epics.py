"""Tests for epic management — parent/child hierarchy and progress."""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.epics import (
    EpicProgress,
    add_sub_feature,
    check_epic_completion,
    create_epic,
    epic_progress,
)
from devflow.core.models import Feature, FeatureStatus, WorkflowState, generate_feature_id
from devflow.core.workflow import load_state, save_state


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestGenerateFeatureId:
    def test_basic(self) -> None:
        fid = generate_feature_id("add user auth")
        assert fid.startswith("feat-add-user-auth-")

    def test_strips_special_chars(self) -> None:
        fid = generate_feature_id("fix: bug #123")
        assert ":" not in fid
        assert "#" not in fid

    def test_empty_description(self) -> None:
        fid = generate_feature_id("")
        assert fid.startswith("feat-")


class TestEpicProgress:
    def test_all_done(self) -> None:
        p = EpicProgress(total=3, done=3, in_progress=0, failed=0, pending=0)
        assert p.all_done is True
        assert p.ratio == 1.0

    def test_partial(self) -> None:
        p = EpicProgress(total=4, done=2, in_progress=1, failed=0, pending=1)
        assert p.all_done is False
        assert p.ratio == 0.5

    def test_empty(self) -> None:
        p = EpicProgress(total=0, done=0, in_progress=0, failed=0, pending=0)
        assert p.all_done is False
        assert p.ratio == 0.0


class TestEpicProgressFromState:
    def test_computes_from_children(self) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-001", description="epic", phases=[])
        state.add_feature(epic)

        statuses = [FeatureStatus.DONE, FeatureStatus.IMPLEMENTING, FeatureStatus.PENDING]
        for i, status in enumerate(statuses):
            sub = Feature(
                id=f"sub-{i}", description=f"sub {i}",
                status=status, parent_id="epic-001", phases=[],
            )
            state.add_feature(sub)

        progress = epic_progress(state, "epic-001")
        assert progress.total == 3
        assert progress.done == 1
        assert progress.in_progress == 1
        assert progress.pending == 1


class TestWorkflowStateHierarchy:
    def test_children_of(self) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-001", description="epic", phases=[])
        sub = Feature(id="sub-001", description="sub", parent_id="epic-001", phases=[])
        standalone = Feature(id="feat-001", description="standalone", phases=[])
        state.add_feature(epic)
        state.add_feature(sub)
        state.add_feature(standalone)

        children = state.children_of("epic-001")
        assert len(children) == 1
        assert children[0].id == "sub-001"

    def test_is_epic(self) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-001", description="epic", phases=[])
        sub = Feature(id="sub-001", description="sub", parent_id="epic-001", phases=[])
        state.add_feature(epic)
        state.add_feature(sub)

        assert state.is_epic("epic-001") is True
        assert state.is_epic("sub-001") is False

    def test_epics_list(self) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-001", description="epic", phases=[])
        sub = Feature(id="sub-001", description="sub", parent_id="epic-001", phases=[])
        standalone = Feature(id="feat-001", description="standalone", phases=[])
        state.add_feature(epic)
        state.add_feature(sub)
        state.add_feature(standalone)

        epics = state.epics()
        assert len(epics) == 1
        assert epics[0].id == "epic-001"


class TestCreateEpic:
    def test_creates_epic_and_subs(self, project_dir: Path) -> None:
        epic, subs = create_epic(
            "backend refactor",
            ["extract service layer", "add repository pattern"],
            base=project_dir,
        )
        assert epic.phases == []
        assert len(subs) == 2
        assert all(s.parent_id == epic.id for s in subs)
        assert all(len(s.phases) > 0 for s in subs)

        # Verify persisted.
        state = load_state(project_dir)
        assert state.get_feature(epic.id) is not None
        assert len(state.children_of(epic.id)) == 2

    def test_epic_has_no_phases(self, project_dir: Path) -> None:
        epic, _ = create_epic("big feature", ["step 1"], base=project_dir)
        assert epic.phases == []


class TestAddSubFeature:
    def test_adds_to_existing_epic(self, project_dir: Path) -> None:
        epic, _ = create_epic("epic", ["sub 1"], base=project_dir)
        new_sub = add_sub_feature(epic.id, "sub 2", base=project_dir)
        assert new_sub.parent_id == epic.id

        state = load_state(project_dir)
        assert len(state.children_of(epic.id)) == 2

    def test_raises_for_missing_epic(self, project_dir: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            add_sub_feature("nonexistent", "sub", base=project_dir)


class TestCheckEpicCompletion:
    def test_marks_epic_done_when_all_children_done(self, project_dir: Path) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-done", description="epic", phases=[])
        sub1 = Feature(
            id="sub-d1", description="s1", parent_id="epic-done",
            status=FeatureStatus.DONE, phases=[],
        )
        sub2 = Feature(
            id="sub-d2", description="s2", parent_id="epic-done",
            status=FeatureStatus.DONE, phases=[],
        )
        state.add_feature(epic)
        state.add_feature(sub1)
        state.add_feature(sub2)
        save_state(state, project_dir)

        assert check_epic_completion("epic-done", project_dir) is True
        reloaded = load_state(project_dir)
        assert reloaded.get_feature("epic-done").status == FeatureStatus.DONE

    def test_does_not_mark_done_with_pending_children(self, project_dir: Path) -> None:
        state = WorkflowState()
        epic = Feature(id="epic-partial", description="epic", phases=[])
        sub1 = Feature(
            id="sub-p1", description="s1", parent_id="epic-partial",
            status=FeatureStatus.DONE, phases=[],
        )
        sub2 = Feature(
            id="sub-p2", description="s2", parent_id="epic-partial",
            status=FeatureStatus.IMPLEMENTING, phases=[],
        )
        state.add_feature(epic)
        state.add_feature(sub1)
        state.add_feature(sub2)
        save_state(state, project_dir)

        assert check_epic_completion("epic-partial", project_dir) is False

    def test_noop_for_already_done_epic(self, project_dir: Path) -> None:
        state = WorkflowState()
        epic = Feature(
            id="epic-already", description="epic",
            status=FeatureStatus.DONE, phases=[],
        )
        state.add_feature(epic)
        save_state(state, project_dir)

        assert check_epic_completion("epic-already", project_dir) is False
