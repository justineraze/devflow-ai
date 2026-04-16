"""Tests for devflow.integrations.git.commit_message — Conventional Commits templating."""

from devflow.core.models import Feature, FeatureMetadata
from devflow.integrations.git.commit_message import build_commit_message, build_pr_title


class TestBuildPrTitle:
    def test_feat_prefix_for_standard_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="Add user authentication",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: add user authentication"

    def test_fix_prefix_for_quick_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="broken login redirect",
            workflow="quick",
        )
        assert build_pr_title(feature) == "fix: broken login redirect"

    def test_strips_trailing_punctuation(self) -> None:
        feature = Feature(
            id="f-001", description="Add dark mode!",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: add dark mode"

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
        assert build_pr_title(feature) == "feat: add OAuth support"

    def test_description_is_lowercase(self) -> None:
        # Conventional Commits: description must be lowercase.
        feature = Feature(
            id="f-001", description="Add user authentication",
            workflow="standard",
        )
        title = build_pr_title(feature)
        assert title == "feat: add user authentication"

    def test_description_with_colon_does_not_create_double_colon(self) -> None:
        # Regression: descriptions containing ":" were producing titles like
        # "feat: PostCompact hook: re-inject …" which looks like two type prefixes.
        feature = Feature(
            id="f-001", description="PostCompact hook: re-inject devflow context",
            workflow="standard",
        )
        title = build_pr_title(feature)
        # Only one colon after the type prefix.
        assert title.count(":") == 1


class TestBuildCommitMessage:
    def test_no_suffix_matches_pr_title(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        assert build_commit_message(feature) == "feat: add user auth"

    def test_with_phase_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "feat: add user auth — implementing"

    def test_with_leftover_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="leftover changes")
        assert msg == "feat: add user auth — leftover changes"

    def test_quick_workflow_uses_fix_prefix(self) -> None:
        feature = Feature(
            id="f-001", description="broken login", workflow="quick",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "fix: broken login — implementing"

    def test_truncates_at_word_boundary(self) -> None:
        long = "Add something very long indeed going past the limit"
        feature = Feature(id="f-001", description=long, workflow="standard")
        msg = build_commit_message(feature, suffix="implementing")
        assert len(msg) <= 70
        assert not msg.endswith(" ")

    def test_with_scope(self) -> None:
        feature = Feature(
            id="f-001", description="Add caching layer", workflow="standard",
            metadata=FeatureMetadata(scope="runner"),
        )
        assert build_commit_message(feature) == "feat(runner): add caching layer"

    def test_scope_in_fix_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="broken login", workflow="quick",
            metadata=FeatureMetadata(scope="gate"),
        )
        assert build_commit_message(feature) == "fix(gate): broken login"

    def test_no_scope_omits_parentheses(self) -> None:
        feature = Feature(id="f-001", description="Add user auth", workflow="standard")
        assert "(" not in build_commit_message(feature)
