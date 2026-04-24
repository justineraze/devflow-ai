"""Tests for devflow.integrations.git.smart_messages — AI-generated git messages."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from devflow.core.models import Feature
from devflow.integrations.git.smart_messages import (
    _truncate_diff,
    generate_commit_message,
    generate_feature_title,
    generate_pr_body,
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
    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_returns_haiku_result(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "add dark mode toggle"
        result = generate_feature_title("Ajouter le dark mode avec un toggle dans les settings")
        assert result == "add dark mode toggle"

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_strips_quotes_and_period(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = '"add dark mode toggle."'
        result = generate_feature_title("something long")
        assert result == "add dark mode toggle"

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_fallback_on_failure(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        result = generate_feature_title("First line of the prompt\nSecond line")
        assert result == "First line of the prompt"

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_fallback_truncates_to_80(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        long_prompt = "A" * 120
        result = generate_feature_title(long_prompt)
        assert len(result) == 80

    @patch("devflow.integrations.git.smart_messages._call_haiku")
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
    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_returns_haiku_message(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+def foo():\n+    pass"
        mock_haiku.return_value = "feat(auth): add login endpoint"
        result = generate_commit_message(self._feature())
        assert result == "feat(auth): add login endpoint"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_haiku")
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
    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_strips_quotes_from_haiku(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = '"feat: add auth"'
        result = generate_commit_message(self._feature())
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_rejects_too_long_haiku_result(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = "x" * 101
        result = generate_commit_message(self._feature())
        # Falls back to template
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_takes_only_first_line(
        self, mock_haiku: MagicMock, mock_diff: MagicMock,
    ) -> None:
        mock_diff.return_value = "+code"
        mock_haiku.return_value = "feat: add auth\n\nBody paragraph"
        result = generate_commit_message(self._feature())
        assert result == "feat: add auth"

    @patch("devflow.integrations.git.smart_messages._get_staged_diff")
    @patch("devflow.integrations.git.smart_messages._call_haiku")
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

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_returns_haiku_body_with_footer(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "## Summary\n- Added auth\n"
        result = generate_pr_body(self._feature(), plan="some plan", diff_stat="+10 -2")
        assert "## Summary" in result
        assert "devflow-ai" in result

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_fallback_on_failure(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = None
        result = generate_pr_body(self._feature())
        # Should use the deterministic template
        assert "## Summary" in result
        assert "Add auth" in result

    @patch("devflow.integrations.git.smart_messages._call_haiku")
    def test_sends_plan_and_diff_stat(self, mock_haiku: MagicMock) -> None:
        mock_haiku.return_value = "## Summary\n- Done"
        generate_pr_body(self._feature(), plan="Plan text", diff_stat="+5 files")
        user_arg = mock_haiku.call_args[0][1]
        assert "Plan text" in user_arg
        assert "+5 files" in user_arg
