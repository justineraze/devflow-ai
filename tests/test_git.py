"""Tests for devflow.git — git operations."""

from unittest.mock import MagicMock, patch

from devflow.git import commit_changes, has_commits_ahead
from devflow.models import Feature, FeatureStatus


class TestCommitChanges:
    @patch("devflow.git.subprocess.run")
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

    @patch("devflow.git.subprocess.run")
    def test_skips_when_nothing_to_commit(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=0),  # git diff --cached --quiet (clean)
        ]
        result = commit_changes("feat: nothing")
        assert result is False
        assert mock_run.call_count == 2


class TestHasCommitsAhead:
    @patch("devflow.git.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.git.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False


class TestPushAndCreatePr:
    @patch("devflow.git.subprocess.run")
    def test_catchall_commit_uses_chore_prefix(self, mock_run: MagicMock) -> None:
        from devflow.git import push_and_create_pr

        feature = Feature(
            id="feat-test-001", description="Add auth",
            workflow="standard", status=FeatureStatus.DONE, phases=[],
        )
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A (from commit_changes)
            MagicMock(returncode=1),  # git diff --cached --quiet
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0, stdout="1\n"),  # rev-list (has_commits_ahead)
            MagicMock(returncode=0),  # git push
            MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # gh pr
        ]
        url = push_and_create_pr(feature, "feat/feat-test-001")
        assert url == "https://github.com/pr/1"
        commit_call = mock_run.call_args_list[2]
        commit_msg = commit_call[0][0][-1]
        assert "chore(" in commit_msg
