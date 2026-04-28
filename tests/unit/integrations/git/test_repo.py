"""Tests for devflow.integrations.git.repo — git subprocess wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.integrations.git.repo import (
    branch_name,
    commit_changes,
    detect_base_branch,
    get_orphan_feature_branches,
    get_untracked_files,
    has_commits_ahead,
)


class TestBranchName:
    def test_strips_feat_prefix(self) -> None:
        assert branch_name("feat-add-caching-0415") == "feat/add-caching-0415"

    def test_no_prefix_preserved(self) -> None:
        assert branch_name("add-caching-0415") == "feat/add-caching-0415"

    def test_quick_fix_id(self) -> None:
        assert branch_name("feat-fix-login-1234") == "feat/fix-login-1234"


class TestCommitChanges:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_commits_when_changes_exist(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=1),  # git diff --cached --quiet (changes)
            MagicMock(returncode=0),  # git commit
        ]
        result = commit_changes("feat: test commit")
        assert result is True
        commit_call = mock_run.call_args_list[2]
        assert "feat: test commit" in commit_call[0][0]

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_skips_when_nothing_to_commit(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=0),  # git diff --cached --quiet (clean)
        ]
        result = commit_changes("feat: nothing")
        assert result is False
        assert mock_run.call_count == 2


class TestCommitChangesExclude:
    """Integration tests with a real tmp git repo for the exclude pathspec."""

    def _init_repo(self, tmp_path: Path) -> Path:
        """Create a minimal git repo with one committed file."""
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@devflow.ai"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "tracked.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        return tmp_path

    def test_excluded_file_not_committed(
        self, tmp_path: Path, monkeypatch: MagicMock,
    ) -> None:
        repo = self._init_repo(tmp_path)
        monkeypatch.chdir(repo)

        (repo / "scratch.md").write_text("user notes")
        (repo / "tracked.py").write_text("x = 2\n")

        assert commit_changes("feat: update", exclude=["scratch.md"]) is True

        log = subprocess.run(
            ["git", "show", "--stat", "--format="],
            cwd=repo, capture_output=True, text=True,
        )
        assert "tracked.py" in log.stdout
        assert "scratch.md" not in log.stdout

    def test_no_exclude_commits_everything(
        self, tmp_path: Path, monkeypatch: MagicMock,
    ) -> None:
        repo = self._init_repo(tmp_path)
        monkeypatch.chdir(repo)

        (repo / "scratch.md").write_text("user notes")
        assert commit_changes("feat: all") is True

        log = subprocess.run(
            ["git", "show", "--stat", "--format="],
            cwd=repo, capture_output=True, text=True,
        )
        assert "scratch.md" in log.stdout


class TestGetUntrackedFiles:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_returns_untracked_paths(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="scratch.md\nnotes.txt\n",
        )
        assert get_untracked_files() == ["scratch.md", "notes.txt"]

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_empty_when_no_untracked(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert get_untracked_files() == []


class TestDetectBaseBranch:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_parses_head_branch(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="* remote origin\n  HEAD branch: develop\n  Remote branches:\n",
        )
        assert detect_base_branch() == "develop"

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_returns_main_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        assert detect_base_branch() == "main"

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_returns_main_when_no_head_line(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="* remote origin\n  Fetch URL: ...\n",
        )
        assert detect_base_branch() == "main"


class TestHasCommitsAhead:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False


class TestGetOrphanFeatureBranches:
    """Real-repo integration tests for orphan branch detection."""

    def _init_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@devflow.ai"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "x.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True,
        )
        return tmp_path

    def test_detects_branch_with_zero_commits_ahead(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        # Create a branch but stay on main, no commits added.
        subprocess.run(
            ["git", "branch", "feat/empty-orphan"],
            cwd=repo, capture_output=True,
        )
        orphans = get_orphan_feature_branches(cwd=repo)
        assert "feat/empty-orphan" in orphans

    def test_skips_branch_with_commits(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        subprocess.run(
            ["git", "checkout", "-b", "feat/with-work"],
            cwd=repo, capture_output=True,
        )
        (repo / "y.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: y"], cwd=repo, capture_output=True,
        )
        # Switch back so it isn't the current branch (which is excluded).
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True)

        orphans = get_orphan_feature_branches(cwd=repo)
        assert "feat/with-work" not in orphans

    def test_skips_current_branch(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        # Create and stay on the orphan branch.
        subprocess.run(
            ["git", "checkout", "-b", "feat/current-orphan"],
            cwd=repo, capture_output=True,
        )
        orphans = get_orphan_feature_branches(cwd=repo)
        assert "feat/current-orphan" not in orphans

    def test_only_matches_prefix(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        subprocess.run(
            ["git", "branch", "release/1.0"],
            cwd=repo, capture_output=True,
        )
        orphans = get_orphan_feature_branches(cwd=repo)
        assert "release/1.0" not in orphans


# ---------------------------------------------------------------------------
# Worktree helpers (create/list/remove + main_repo_root from a worktree)
# ---------------------------------------------------------------------------


def _init_repo_with_commit(path: Path) -> None:
    """Initialize a bare git repo with one commit (used by worktree tests)."""
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
def worktree_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary git repo with one commit, ready for worktree operations."""
    _init_repo_with_commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestMainRepoRoot:
    def test_returns_repo_root(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import main_repo_root

        root = main_repo_root(worktree_repo)
        assert root == worktree_repo

    def test_returns_main_root_from_worktree(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree, main_repo_root

        _, wt_path = create_worktree("feat-test-001", cwd=worktree_repo)
        root = main_repo_root(wt_path)
        assert root == worktree_repo


class TestCreateWorktree:
    def test_creates_worktree_dir(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree

        branch, wt_path = create_worktree("feat-wt-001", cwd=worktree_repo)
        assert wt_path.exists()
        assert wt_path.is_dir()
        assert branch == branch_name("feat-wt-001")

    def test_worktree_has_files(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree

        _, wt_path = create_worktree("feat-wt-002", cwd=worktree_repo)
        assert (wt_path / "README.md").exists()

    def test_idempotent(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree

        _, path1 = create_worktree("feat-wt-003", cwd=worktree_repo)
        _, path2 = create_worktree("feat-wt-003", cwd=worktree_repo)
        assert path1 == path2

    def test_path_under_devflow(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree

        _, wt_path = create_worktree("feat-wt-004", cwd=worktree_repo)
        assert ".devflow" in str(wt_path)
        assert ".worktrees" in str(wt_path)


class TestRemoveWorktree:
    def test_removes_existing(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree, remove_worktree

        _, wt_path = create_worktree("feat-rm-001", cwd=worktree_repo)
        assert wt_path.exists()
        assert remove_worktree("feat-rm-001", cwd=worktree_repo) is True
        assert not wt_path.exists()

    def test_noop_for_missing(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import remove_worktree

        assert remove_worktree("feat-nonexistent", cwd=worktree_repo) is True


class TestListWorktrees:
    def test_lists_main_and_linked(self, worktree_repo: Path) -> None:
        from devflow.integrations.git.repo import create_worktree, list_worktrees

        create_worktree("feat-list-001", cwd=worktree_repo)
        wts = list_worktrees(cwd=worktree_repo)
        paths = [wt["path"] for wt in wts]
        assert str(worktree_repo) in paths
        assert len(wts) >= 2
