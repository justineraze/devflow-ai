"""Tests for devflow.integrations.git.repo — git subprocess wrappers."""

from unittest.mock import MagicMock, patch

from devflow.integrations.git.repo import branch_name, commit_changes, has_commits_ahead


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


class TestHasCommitsAhead:
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False
