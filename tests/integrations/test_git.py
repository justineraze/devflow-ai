"""Tests for devflow.integrations.git — git operations."""

from unittest.mock import MagicMock, patch

from devflow.core.models import Feature, FeatureStatus, PhaseRecord, PhaseName, PhaseStatus
from devflow.integrations.git import (
    build_commit_message,
    build_pr_title,
    commit_changes,
    compose_pr_body,
    compose_pr_title,
    has_commits_ahead,
)


class TestComposePrTitle:
    def test_short_title_no_ellipsis(self) -> None:
        """Short description fits within _MAX_LEN — no ellipsis appended."""
        result = compose_pr_title("feat", "Add auth")
        assert result == "feat: Add auth"
        assert "…" not in result

    def test_long_title_word_boundary_with_ellipsis(self) -> None:
        """Long description truncated at last word boundary, ellipsis appended, len ≤ 70."""
        long_desc = "Add a very long feature description that goes on and on and exceeds the limit easily"
        result = compose_pr_title("feat", long_desc)
        assert len(result) <= 70
        assert result.endswith("…")
        # The character just before ellipsis must not be a space (word boundary).
        assert result[-2] != " "

    def test_preserves_full_description_when_short(self) -> None:
        """Exact short description is preserved verbatim (capitalized)."""
        result = compose_pr_title("fix", "broken login redirect")
        assert result == "fix: Broken login redirect"

    def test_with_suffix_short(self) -> None:
        """Suffix appended with em-dash when result fits within _MAX_LEN."""
        result = compose_pr_title("feat", "Add auth", suffix="implementing")
        assert result == "feat: Add auth — implementing"
        assert "…" not in result

    def test_with_suffix_truncated(self) -> None:
        """Long title + suffix still respects _MAX_LEN with ellipsis."""
        long_desc = "Add something very long indeed going past the limit completely"
        result = compose_pr_title("feat", long_desc, suffix="implementing")
        assert len(result) <= 70
        assert result.endswith("…")


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


# ---------------------------------------------------------------------------
# Helpers for compose_pr_body tests
# ---------------------------------------------------------------------------

_SHORT_DESC = "Add user authentication support"
_LONG_DESC = (
    "Add user authentication support with OAuth2. "
    "This involves integrating the third-party identity provider, "
    "updating the session middleware, adding the callback routes, "
    "and writing the integration tests to verify the full login flow "
    "end-to-end including token refresh and logout scenarios."
)


def _make_feature(
    desc: str = _SHORT_DESC,
    metadata: dict | None = None,
    phases: list[PhaseRecord] | None = None,
) -> Feature:
    return Feature(
        id="f-001",
        description=desc,
        workflow="standard",
        metadata=metadata or {},
        phases=phases or [],
    )


def _done_phase(name: PhaseName, output: str) -> PhaseRecord:
    return PhaseRecord(name=name, status=PhaseStatus.DONE, output=output)


class TestComposePrBody:
    def test_uses_pr_summary_metadata(self) -> None:
        """pr_summary metadata takes priority over description."""
        feature = _make_feature(
            desc="Some raw verbose prompt text that goes on forever.",
            metadata={"pr_summary": "Add OAuth2 login with token refresh."},
        )
        body = compose_pr_body(feature)
        assert "Add OAuth2 login with token refresh." in body
        assert "Some raw verbose prompt text" not in body

    def test_no_context_section_when_metadata_present(self) -> None:
        """When pr_summary metadata is set, no ## Context section is added."""
        feature = _make_feature(desc=_LONG_DESC, metadata={"pr_summary": "Short summary."})
        body = compose_pr_body(feature)
        assert "## Context" not in body

    def test_derives_summary_from_first_sentence(self) -> None:
        """Without metadata, summary is the first sentence of the description."""
        multi_sentence = "Add caching layer. This reduces DB load. Also improves latency."
        feature = _make_feature(desc=multi_sentence)
        body = compose_pr_body(feature)
        # Only the first sentence in Summary.
        assert "## Summary" in body
        assert "Add caching layer." in body
        # Second sentence must not appear in Summary (it may appear in Context).
        lines = body.split("\n")
        summary_idx = lines.index("## Summary")
        # The summary paragraph follows directly; second sentence is not right after it.
        summary_paragraph = lines[summary_idx + 2]  # blank line then content
        assert "This reduces DB load" not in summary_paragraph

    def test_context_section_for_long_descriptions(self) -> None:
        """Long descriptions (> 240 chars) get a ## Context section."""
        assert len(_LONG_DESC) > 240  # sanity check
        feature = _make_feature(desc=_LONG_DESC)
        body = compose_pr_body(feature)
        assert "## Context" in body
        assert _LONG_DESC in body

    def test_no_context_for_short_descriptions(self) -> None:
        """Short descriptions (≤ 240 chars) produce no ## Context section."""
        assert len(_SHORT_DESC) <= 240  # sanity check
        feature = _make_feature(desc=_SHORT_DESC)
        body = compose_pr_body(feature)
        assert "## Context" not in body

    def test_renders_plan_section(self) -> None:
        """A completed planning phase output appears under ## Plan."""
        planning_output = "## Plan\n\nStep 1: scaffold\nStep 2: implement"
        feature = _make_feature(
            phases=[_done_phase(PhaseName.PLANNING, planning_output)],
        )
        body = compose_pr_body(feature)
        assert "## Plan" in body
        assert planning_output in body

    def test_renders_gate_section(self) -> None:
        """A completed gate phase output appears under ## Quality gate."""
        gate_output = "ruff: OK\npytest: 42 passed"
        feature = _make_feature(
            phases=[_done_phase(PhaseName.GATE, gate_output)],
        )
        body = compose_pr_body(feature)
        assert "## Quality gate" in body
        assert gate_output in body

    def test_renders_plan_and_gate_sections(self) -> None:
        """Both Plan and Quality gate sections rendered when both phases done."""
        planning_output = "Step 1: do the thing"
        gate_output = "All checks passed"
        feature = _make_feature(
            phases=[
                _done_phase(PhaseName.PLANNING, planning_output),
                _done_phase(PhaseName.GATE, gate_output),
            ],
        )
        body = compose_pr_body(feature)
        assert "## Plan" in body
        assert planning_output in body
        assert "## Quality gate" in body
        assert gate_output in body

    def test_footer_always_present(self) -> None:
        """devflow-ai footer link is always appended."""
        feature = _make_feature()
        body = compose_pr_body(feature)
        assert "devflow-ai" in body
        assert "---" in body
