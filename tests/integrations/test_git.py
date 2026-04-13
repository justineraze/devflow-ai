"""Tests for devflow.integrations.git — git operations."""

from unittest.mock import MagicMock, patch

from devflow.core.models import Feature, FeatureStatus
from devflow.integrations.git import (
    build_commit_message,
    build_pr_title,
    commit_changes,
    has_commits_ahead,
)


class TestBuildPrTitle:
    def test_feat_prefix_for_standard_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="Add user authentication",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add user authentication"

    def test_fix_prefix_for_quick_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="broken login redirect",
            workflow="quick",
        )
        assert build_pr_title(feature) == "fix: Broken login redirect"

    def test_strips_trailing_punctuation(self) -> None:
        feature = Feature(
            id="f-001", description="Add dark mode!",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add dark mode"

    def test_truncates_long_description(self) -> None:
        long = "Add a very long feature description that goes on and on and exceeds the limit"
        feature = Feature(id="f-001", description=long, workflow="standard")
        title = build_pr_title(feature)
        assert len(title) <= 70
        # Should break on word boundary.
        assert not title.endswith(" ")

    def test_preserves_acronyms(self) -> None:
        feature = Feature(
            id="f-001", description="Add OAuth support",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add OAuth support"


class TestBuildCommitMessage:
    def test_no_suffix_matches_pr_title(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        assert build_commit_message(feature) == "feat: Add user auth"

    def test_with_phase_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "feat: Add user auth — implementing"

    def test_with_leftover_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="leftover changes")
        assert msg == "feat: Add user auth — leftover changes"

    def test_quick_workflow_uses_fix_prefix(self) -> None:
        feature = Feature(
            id="f-001", description="broken login", workflow="quick",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "fix: Broken login — implementing"

    def test_truncates_at_word_boundary(self) -> None:
        long = "Add something very long indeed going past the limit"
        feature = Feature(id="f-001", description=long, workflow="standard")
        msg = build_commit_message(feature, suffix="implementing")
        assert len(msg) <= 70
        assert not msg.endswith(" ")


class TestCommitChanges:
    @patch("devflow.integrations.git.subprocess.run")
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

    @patch("devflow.integrations.git.subprocess.run")
    def test_skips_when_nothing_to_commit(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=0),  # git diff --cached --quiet (clean)
        ]
        result = commit_changes("feat: nothing")
        assert result is False
        assert mock_run.call_count == 2


class TestHasCommitsAhead:
    @patch("devflow.integrations.git.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.integrations.git.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False


class TestPushAndCreatePr:
    @patch("devflow.integrations.git.subprocess.run")
    def test_uses_conventional_commit_title(self, mock_run: MagicMock) -> None:
        from devflow.integrations.git import push_and_create_pr

        feature = Feature(
            id="feat-test-001", description="Add auth",
            workflow="standard", status=FeatureStatus.DONE, phases=[],
        )
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=1),  # git diff --cached --quiet (changes)
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0, stdout="1\n"),  # rev-list
            MagicMock(returncode=0),  # git push
            MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # gh pr
        ]
        url = push_and_create_pr(feature, "feat/feat-test-001")
        assert url == "https://github.com/pr/1"

        # Safety-net commit uses feat: prefix.
        commit_call = mock_run.call_args_list[2]
        commit_msg = commit_call[0][0][-1]
        assert commit_msg.startswith("feat:")

        # PR title uses Conventional Commits format.
        pr_call = mock_run.call_args_list[5]
        pr_args = pr_call[0][0]
        title_idx = pr_args.index("--title") + 1
        assert pr_args[title_idx] == "feat: Add auth"
