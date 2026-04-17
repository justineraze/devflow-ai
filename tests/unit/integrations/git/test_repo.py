"""Tests for devflow.integrations.git.repo — git subprocess wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from devflow.integrations.git.repo import (
    branch_name,
    commit_changes,
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


class TestHasCommitsAhead:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False
