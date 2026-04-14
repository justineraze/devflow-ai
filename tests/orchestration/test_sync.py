"""Tests for devflow sync orchestration."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.orchestration.sync import DirtyWorktreeError, run_sync

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path, features: list[dict]) -> None:
    """Write a minimal state.json with the given features list."""
    import json
    from datetime import datetime

    devflow = tmp_path / ".devflow"
    devflow.mkdir(exist_ok=True)

    now = datetime.now(UTC).isoformat()
    feat_dict = {}
    for f in features:
        fid = f["id"]
        feat_dict[fid] = {
            "id": fid,
            "description": f.get("description", "test feature"),
            "status": f.get("status", "pending"),
            "workflow": "standard",
            "created_at": now,
            "updated_at": now,
            "phases": [],
            "metadata": f.get("metadata", {}),
        }

    state = {"version": 1, "stack": None, "features": feat_dict, "updated_at": now}
    (devflow / "state.json").write_text(json.dumps(state))


def _make_feat_dir(tmp_path: Path, feature_id: str) -> Path:
    """Create a .devflow/<feature_id>/ directory with a dummy artifact."""
    feat_dir = tmp_path / ".devflow" / feature_id
    feat_dir.mkdir(parents=True, exist_ok=True)
    (feat_dir / "planning.md").write_text("# plan")
    return feat_dir


# ---------------------------------------------------------------------------
# Test 1 — dry-run does not mutate
# ---------------------------------------------------------------------------


def test_sync_dry_run_no_mutation(tmp_path: Path) -> None:
    """dry_run=True populates actions list without deleting branches or archiving."""
    _make_state(tmp_path, [{"id": "f-001", "status": "done"}])
    feat_dir = _make_feat_dir(tmp_path, "f-001")

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=False),
        patch("devflow.integrations.git.switch_and_pull_main"),
        patch("devflow.integrations.git.fetch_prune"),
        patch("devflow.integrations.git.get_gone_branches", return_value=["feat/old-branch"]),
        patch("devflow.integrations.git.delete_branch") as mock_del,
        patch("devflow.orchestration.sync._pr_is_merged", return_value=True),
        patch("devflow.orchestration.sync._current_branch", return_value="main"),
    ):
        result = run_sync(project_root=tmp_path, dry_run=True)

    # No branch was actually deleted.
    mock_del.assert_not_called()
    # The gone branch is listed.
    assert "feat/old-branch" in result.branches_deleted
    # Feature is listed as would-archive.
    assert "f-001" in result.features_archived
    # Artifact dir still exists (nothing moved).
    assert feat_dir.exists()
    # Actions log is non-empty.
    assert any("would" in a for a in result.actions)
    assert result.dry_run is True


# ---------------------------------------------------------------------------
# Test 2 — gone branches are deleted
# ---------------------------------------------------------------------------


def test_sync_deletes_gone_branches(tmp_path: Path) -> None:
    """Gone branches are deleted via git branch -D."""
    _make_state(tmp_path, [])

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=False),
        patch("devflow.integrations.git.switch_and_pull_main"),
        patch("devflow.integrations.git.fetch_prune"),
        patch("devflow.integrations.git.get_gone_branches", return_value=["feat/done-feat"]),
        patch("devflow.integrations.git.delete_branch", return_value=True) as mock_del,
        patch("devflow.orchestration.sync._current_branch", return_value="main"),
    ):
        result = run_sync(project_root=tmp_path)

    mock_del.assert_called_once_with("feat/done-feat", cwd=tmp_path)
    assert result.branches_deleted == ["feat/done-feat"]


# ---------------------------------------------------------------------------
# Test 3 — merged features are archived
# ---------------------------------------------------------------------------


def test_sync_archives_merged_features(tmp_path: Path) -> None:
    """Done features with merged PRs are moved to .devflow/.archive/<id>/."""
    _make_state(tmp_path, [{"id": "f-002", "status": "done"}])
    feat_dir = _make_feat_dir(tmp_path, "f-002")

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=False),
        patch("devflow.integrations.git.switch_and_pull_main"),
        patch("devflow.integrations.git.fetch_prune"),
        patch("devflow.integrations.git.get_gone_branches", return_value=[]),
        patch("devflow.orchestration.sync._pr_is_merged", return_value=True),
        patch("devflow.orchestration.sync._current_branch", return_value="main"),
    ):
        result = run_sync(project_root=tmp_path)

    # Source dir moved to archive.
    archive_path = tmp_path / ".devflow" / ".archive" / "f-002"
    assert archive_path.exists(), "Feature should be moved to .archive/"
    assert not feat_dir.exists(), "Original feature dir should be gone"
    assert result.features_archived == ["f-002"]

    # metadata.archived=true persisted in state.
    from devflow.core.workflow import load_state
    state = load_state(tmp_path)
    assert state.features["f-002"].metadata.get("archived") is True


# ---------------------------------------------------------------------------
# Test 4 — features with non-merged PRs are untouched
# ---------------------------------------------------------------------------


def test_sync_skips_non_merged_pr(tmp_path: Path) -> None:
    """Done features whose PR is not merged are not archived."""
    _make_state(tmp_path, [{"id": "f-003", "status": "done"}])
    feat_dir = _make_feat_dir(tmp_path, "f-003")

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=False),
        patch("devflow.integrations.git.switch_and_pull_main"),
        patch("devflow.integrations.git.fetch_prune"),
        patch("devflow.integrations.git.get_gone_branches", return_value=[]),
        patch("devflow.orchestration.sync._pr_is_merged", return_value=False),
        patch("devflow.orchestration.sync._current_branch", return_value="main"),
    ):
        result = run_sync(project_root=tmp_path)

    assert feat_dir.exists(), "Feature dir should be untouched"
    assert result.features_archived == []

    from devflow.core.workflow import load_state
    state = load_state(tmp_path)
    assert not state.features["f-003"].metadata.get("archived")


# ---------------------------------------------------------------------------
# Test 5 — refuses to run if working tree is dirty
# ---------------------------------------------------------------------------


def test_sync_refuses_dirty_worktree(tmp_path: Path) -> None:
    """DirtyWorktreeError is raised when working tree is dirty; no ops run."""
    _make_state(tmp_path, [])

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=True),
        patch("devflow.integrations.git.switch_and_pull_main") as mock_pull,
        patch("devflow.integrations.git.fetch_prune") as mock_fetch,
        pytest.raises(DirtyWorktreeError),
    ):
        run_sync(project_root=tmp_path)

    mock_pull.assert_not_called()
    mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6 — keep_artifacts skips archiving
# ---------------------------------------------------------------------------


def test_keep_artifacts_skips_archiving(tmp_path: Path) -> None:
    """With keep_artifacts=True, gone branches are deleted but features are not archived."""
    _make_state(tmp_path, [{"id": "f-004", "status": "done"}])
    feat_dir = _make_feat_dir(tmp_path, "f-004")

    with (
        patch("devflow.integrations.git.is_worktree_dirty", return_value=False),
        patch("devflow.integrations.git.switch_and_pull_main"),
        patch("devflow.integrations.git.fetch_prune"),
        patch("devflow.integrations.git.get_gone_branches", return_value=["feat/f-004"]),
        patch("devflow.integrations.git.delete_branch", return_value=True) as mock_del,
        patch("devflow.orchestration.sync._pr_is_merged") as mock_pr,
        patch("devflow.orchestration.sync._current_branch", return_value="main"),
    ):
        result = run_sync(project_root=tmp_path, keep_artifacts=True)

    # Branch was deleted.
    mock_del.assert_called_once()
    assert result.branches_deleted == ["feat/f-004"]

    # PR check never called — step 5 skipped.
    mock_pr.assert_not_called()

    # Feature artifacts untouched.
    assert feat_dir.exists()
    assert result.features_archived == []

    # No .archive dir created.
    archive_dir = tmp_path / ".devflow" / ".archive"
    assert not archive_dir.exists()
