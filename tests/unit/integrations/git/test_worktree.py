"""Tests for git worktree helpers and state file locking."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devflow.integrations.git.repo import (
    branch_name,
    create_worktree,
    list_worktrees,
    main_repo_root,
    remove_worktree,
)


def _init_repo(path: Path) -> None:
    """Initialize a bare git repo with one commit."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary git repo with one commit."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestMainRepoRoot:
    def test_returns_repo_root(self, git_repo: Path) -> None:
        root = main_repo_root(git_repo)
        assert root == git_repo

    def test_returns_main_root_from_worktree(self, git_repo: Path) -> None:
        _, wt_path = create_worktree("feat-test-001", cwd=git_repo)
        root = main_repo_root(wt_path)
        assert root == git_repo


class TestCreateWorktree:
    def test_creates_worktree_dir(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree("feat-wt-001", cwd=git_repo)
        assert wt_path.exists()
        assert wt_path.is_dir()
        assert branch == branch_name("feat-wt-001")

    def test_worktree_has_files(self, git_repo: Path) -> None:
        _, wt_path = create_worktree("feat-wt-002", cwd=git_repo)
        assert (wt_path / "README.md").exists()

    def test_idempotent(self, git_repo: Path) -> None:
        _, path1 = create_worktree("feat-wt-003", cwd=git_repo)
        _, path2 = create_worktree("feat-wt-003", cwd=git_repo)
        assert path1 == path2

    def test_path_under_devflow(self, git_repo: Path) -> None:
        _, wt_path = create_worktree("feat-wt-004", cwd=git_repo)
        assert ".devflow" in str(wt_path)
        assert ".worktrees" in str(wt_path)


class TestRemoveWorktree:
    def test_removes_existing(self, git_repo: Path) -> None:
        _, wt_path = create_worktree("feat-rm-001", cwd=git_repo)
        assert wt_path.exists()
        assert remove_worktree("feat-rm-001", cwd=git_repo) is True
        assert not wt_path.exists()

    def test_noop_for_missing(self, git_repo: Path) -> None:
        assert remove_worktree("feat-nonexistent", cwd=git_repo) is True


class TestListWorktrees:
    def test_lists_main_and_linked(self, git_repo: Path) -> None:
        create_worktree("feat-list-001", cwd=git_repo)
        wts = list_worktrees(cwd=git_repo)
        paths = [wt["path"] for wt in wts]
        assert str(git_repo) in paths
        assert len(wts) >= 2


class TestStateLock:
    def test_mutate_feature_is_safe(self, git_repo: Path) -> None:
        """Verify mutate_feature acquires the lock (non-concurrent sanity check)."""
        from devflow.core.models import Feature, FeatureStatus
        from devflow.core.workflow import load_state, mutate_feature, save_state

        state = load_state(git_repo)
        feature = Feature(
            id="feat-lock-001",
            description="test locking",
            status=FeatureStatus.PENDING,
            phases=[],
        )
        state.add_feature(feature)
        save_state(state, git_repo)

        with mutate_feature("feat-lock-001", git_repo) as feat:
            assert feat is not None
            feat.description = "updated"

        reloaded = load_state(git_repo)
        assert reloaded.get_feature("feat-lock-001").description == "updated"

    def test_lock_file_created(self, git_repo: Path) -> None:
        from devflow.core.workflow import _state_lock

        with _state_lock(git_repo):
            lock_path = git_repo / ".devflow" / "state.lock"
            assert lock_path.exists()
