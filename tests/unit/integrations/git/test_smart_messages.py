"""Tests for devflow.integrations.git.smart_messages — AI-generated git messages."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from devflow.core.models import Feature
from devflow.integrations.git.smart_messages import (
    _CC_PREFIX_RE,
    _truncate_diff,
    generate_commit_message,
    generate_feature_title,
    generate_pr_body,
    generate_pr_title,
)

# ---------------------------------------------------------------------------
# _truncate_diff
# ---------------------------------------------------------------------------


class TestTruncateDiff:
    def test_short_diff_unchanged(self) -> None:
        diff = "line1\nline2\nline3"
        assert _truncate_diff(diff, max_lines=10) == diff

    def test_long_diff_truncated(self) -> None:
        diff = "\n".join(f"line{i}" for i in range(100))
        result = _truncate_diff(diff, max_lines=10)
        assert result.endswith("… (truncated)")
        # 10 lines + blank + notice
        assert result.count("\n") == 11

    def test_exact_limit_not_truncated(self) -> None:
        diff = "\n".join(f"line{i}" for i in range(10))
        assert _truncate_diff(diff, max_lines=10) == diff


# ---------------------------------------------------------------------------
# generate_feature_title
# ---------------------------------------------------------------------------


class TestGenerateFeatureTitle:
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_returns_haiku_result(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "add dark mode toggle"
        result = generate_feature_title("Ajouter le dark mode avec un toggle dans les settings")
        assert result == "add dark mode toggle"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_strips_quotes_and_period(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = '"add dark mode toggle."'
        result = generate_feature_title("something long")
        assert result == "add dark mode toggle"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_fallback_on_failure(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        result = generate_feature_title("First line of the prompt\nSecond line")
        assert result == "First line of the prompt"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_fallback_truncates_to_80(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        long_prompt = "A" * 120
        result = generate_feature_title(long_prompt)
        assert len(result) == 80

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_fallback_when_haiku_returns_too_long(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "x" * 100  # > 80 chars
        result = generate_feature_title("Short prompt")
        # Should still use it since <= 80 check is on the result
        # Actually > 80, so it falls back
        assert result == "Short prompt"


# ---------------------------------------------------------------------------
# generate_commit_message
# ---------------------------------------------------------------------------


class TestGenerateCommitMessage:
    def _feature(self, **kwargs: object) -> Feature:
        defaults = {"id": "f-001", "description": "Add auth", "workflow": "standard"}
        defaults.update(kwargs)
        return Feature(**defaults)

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_returns_haiku_message(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+def foo():\n+    pass"
        mock_haiku.return_value = "feat(auth): add login endpoint"
        result = generate_commit_message(self._feature())
        assert result == "feat(auth): add login endpoint"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_fallback_on_haiku_failure(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+something"
        mock_haiku.return_value = None
        result = generate_commit_message(self._feature(), phase="implementing")
        assert result == "feat: add auth — implementing"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    def test_fallback_on_empty_diff(self, mock_diff: MagicMock) -> None:
        mock_diff.return_value = ""
        result = generate_commit_message(self._feature(), phase="fixing")
        assert result == "feat: add auth — fixing"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_strips_quotes_from_haiku(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = '"feat: add auth"'
        result = generate_commit_message(self._feature())
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_rejects_too_long_haiku_result(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = "x" * 101
        result = generate_commit_message(self._feature())
        # Falls back to template
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_takes_only_first_line(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = "feat: add auth\n\nBody paragraph"
        result = generate_commit_message(self._feature())
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_no_phase_suffix_in_fallback(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = ""
        mock_haiku.return_value = None
        result = generate_commit_message(self._feature())
        assert result == "feat: add auth"


# ---------------------------------------------------------------------------
# generate_pr_body
# ---------------------------------------------------------------------------


class TestGeneratePrBody:
    def _feature(self, **kwargs: object) -> Feature:
        defaults = {"id": "f-001", "description": "Add auth", "workflow": "standard"}
        defaults.update(kwargs)
        return Feature(**defaults)

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_returns_haiku_body_with_footer(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "## Summary\n- Added auth\n"
        result = generate_pr_body(self._feature(), plan="some plan", diff_stat="+10 -2")
        assert "## Summary" in result
        assert "devflow-ai" in result

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_fallback_on_failure(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        result = generate_pr_body(self._feature())
        # Should use the deterministic template
        assert "## Summary" in result
        assert "Add auth" in result

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_sends_plan_and_diff_stat(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "## Summary\n- Done"
        generate_pr_body(self._feature(), plan="Plan text", diff_stat="+5 files")
        user_arg = mock_haiku.call_args[0][1]
        assert "Plan text" in user_arg
        assert "+5 files" in user_arg


# ---------------------------------------------------------------------------
# generate_pr_title — Conventional Commits enforcement
# ---------------------------------------------------------------------------


class TestGeneratePrTitle:
    """The PR title must always be a valid Conventional Commits subject.

    Regression: previously the PR title was the truncated user prompt,
    which did not satisfy the ``<type>(<scope>): <description>`` format.
    """

    def _feature(self, **kwargs: object) -> Feature:
        defaults = {"id": "f-001", "description": "Add auth", "workflow": "standard"}
        defaults.update(kwargs)
        return Feature(**defaults)

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_returns_model_title_when_valid_cc_format(
        self, mock_haiku: MagicMock,
    ) -> None:
        mock_haiku.return_value = "feat(auth): add login endpoint"
        result = generate_pr_title(self._feature(), diff="+def login(): pass")
        assert result == "feat(auth): add login endpoint"
        assert _CC_PREFIX_RE.match(result)

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_strips_quotes_and_period(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = '"feat: add login endpoint."'
        result = generate_pr_title(self._feature(), diff="+code")
        assert result == "feat: add login endpoint"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_falls_back_when_model_drops_prefix(
        self, mock_haiku: MagicMock,
    ) -> None:
        # Plain prose without a Conventional Commits prefix → reject.
        mock_haiku.return_value = "add login endpoint"
        result = generate_pr_title(self._feature(), diff="+code")
        # Falls back to template build_pr_title("Add auth").
        assert _CC_PREFIX_RE.match(result), result

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_falls_back_when_model_returns_too_long(
        self, mock_haiku: MagicMock,
    ) -> None:
        mock_haiku.return_value = "feat: " + "x" * 200
        result = generate_pr_title(self._feature(), diff="+code")
        assert _CC_PREFIX_RE.match(result)
        assert len(result) <= 80

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_falls_back_when_model_returns_none(
        self, mock_haiku: MagicMock,
    ) -> None:
        mock_haiku.return_value = None
        result = generate_pr_title(self._feature(), diff="+code")
        assert _CC_PREFIX_RE.match(result)

    def test_falls_back_when_diff_empty(self) -> None:
        # No diff to feed the model → directly use the deterministic template.
        result = generate_pr_title(self._feature(), diff="")
        assert _CC_PREFIX_RE.match(result)

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_takes_only_first_line(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "feat: add login\n\nLong body"
        result = generate_pr_title(self._feature(), diff="+code")
        assert result == "feat: add login"


class TestGenerateFeatureTitleStripsCcPrefix:
    """Feature titles must NOT carry a Conventional Commits prefix.

    Reason: ``build_commit_message`` adds the prefix downstream.  If the
    model leaks one (e.g. emits ``feat: …``), we'd get ``feat: feat: …``.
    """

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_strips_feat_prefix(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "feat: add caching layer"
        result = generate_feature_title("please add caching")
        assert result == "add caching layer"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_strips_fix_with_scope(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "fix(auth): null pointer in login"
        result = generate_feature_title("auth login bug")
        assert result == "null pointer in login"

    @patch("devflow.integrations.git.smart_messages._call_one_shot")
    def test_keeps_clean_title(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "extract planning loop into helper"
        result = generate_feature_title("refactor please")
        assert result == "extract planning loop into helper"
