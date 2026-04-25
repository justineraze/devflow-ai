"""Tests for devflow.integrations.complexity — scoring engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.core.models import ComplexityScore
from devflow.core.security import CRITICAL_PATH_PATTERNS
from devflow.integrations.complexity import (
    _clamp,
    _score_files_touched,
    _score_heuristic,
    _score_integrations,
    _score_scope,
    _score_security,
    _score_via_llm,
    score_complexity,
)


class TestCriticalPathPatterns:
    def test_contains_expected_patterns(self) -> None:
        for pat in ("auth", "secret", "token", "crypto", "payment", "billing", "password"):
            assert pat in CRITICAL_PATH_PATTERNS


# ── Heuristic sub-scorers (unchanged) ────────────────────────────


class TestScoreFilesTouched:
    def test_simple_description_scores_one(self) -> None:
        score = _score_files_touched("fix a bug in the parser", None)
        assert score == 1

    def test_new_module_scores_two(self) -> None:
        score = _score_files_touched("add a new module for notifications", None)
        assert score == 2

    def test_new_subsystem_scores_three(self) -> None:
        score = _score_files_touched("build a new subsystem for billing", None)
        assert score == 3

    def test_overhaul_scores_three(self) -> None:
        score = _score_files_touched("overhaul the authentication layer", None)
        assert score == 3

    def test_small_project_caps_at_one(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"module_{i}.py").write_text(f"# module {i}")
        score = _score_files_touched("add new module for reporting", tmp_path)
        assert score == 1

    def test_large_project_not_capped(self, tmp_path: Path) -> None:
        for i in range(25):
            (tmp_path / f"module_{i}.py").write_text(f"# module {i}")
        score = _score_files_touched("add new module for reporting", tmp_path)
        assert score == 2


class TestScoreIntegrations:
    def test_no_integration_keywords_returns_zero(self) -> None:
        assert _score_integrations("rename the helper function") == 0

    def test_single_keyword_returns_one(self) -> None:
        assert _score_integrations("call the external API endpoint") == 1

    def test_two_keywords_returns_two(self) -> None:
        assert _score_integrations("connect the database and redis cache") == 2

    def test_four_keywords_returns_three(self) -> None:
        result = _score_integrations("integrate database, redis, kafka and s3 storage")
        assert result == 3

    def test_oauth_mention_scores(self) -> None:
        assert _score_integrations("add OAuth login via Google") >= 1


class TestScoreSecurity:
    def test_no_security_terms_returns_zero(self) -> None:
        assert _score_security("add a new report page") == 0

    def test_auth_returns_at_least_one(self) -> None:
        assert _score_security("add authentication to the API") >= 1

    def test_multiple_terms_increases_score(self) -> None:
        score = _score_security("implement auth with token-based permission and RBAC")
        assert score >= 2

    def test_security_extra_patterns_counted(self) -> None:
        assert _score_security("add CORS and CSRF protection") >= 1

    def test_critical_path_patterns_counted(self) -> None:
        assert _score_security("handle payment and billing with crypto") == 2

    def test_four_security_patterns_scores_max(self) -> None:
        assert _score_security("payment billing crypto token auth") == 3


class TestScoreScope:
    def test_minimal_description_low_scope(self) -> None:
        score = _score_scope("fix typo")
        assert score <= 1

    def test_high_scope_verbs_increase_score(self) -> None:
        score = _score_scope("redesign and rewrite the entire authentication flow")
        assert score >= 2

    def test_long_description_adds_bonus(self) -> None:
        long_desc = " ".join(["word"] * 35)
        score = _score_scope(long_desc)
        assert score >= 1

    def test_low_scope_verbs_decrease_score(self) -> None:
        score = _score_scope("minor fix and rename the variable")
        assert score <= 1


# ── Heuristic fallback ───────────────────────────────────────────


class TestScoreHeuristic:
    def test_trivial_description_gives_quick(self) -> None:
        score = _score_heuristic("fix a typo in the README", None)
        assert score.workflow in {"quick", "light"}

    def test_complex_description_gives_standard_or_full(self) -> None:
        score = _score_heuristic(
            "Implement OAuth2 authentication with JWT tokens and RBAC permission system "
            "integrated with the database and Redis cache. Rewrite the auth module.",
            None,
        )
        assert score.workflow in {"standard", "full"}

    def test_returns_complexity_score_model(self) -> None:
        score = _score_heuristic("add a field", None)
        assert isinstance(score, ComplexityScore)
        assert 0 <= score.total <= 12


# ── LLM scorer ───────────────────────────────────────────────────


class TestScoreViaLlm:
    _VALID_JSON = (
        '{"files_touched": 2, "integrations": 1,'
        ' "security": 0, "scope": 3}'
    )

    def test_valid_json_returns_score(self) -> None:
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = self._VALID_JSON
            result = _score_via_llm("some task")
        assert result is not None
        assert result.files_touched == 2
        assert result.integrations == 1
        assert result.security == 0
        assert result.scope == 3

    def test_invalid_json_returns_none(self) -> None:
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = "not json at all"
            result = _score_via_llm("some task")
        assert result is None

    def test_backend_returns_none(self) -> None:
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = None
            result = _score_via_llm("some task")
        assert result is None

    def test_backend_exception_returns_none(self) -> None:
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.side_effect = TimeoutError("too slow")
            result = _score_via_llm("some task")
        assert result is None

    def test_missing_key_returns_none(self) -> None:
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = '{"files_touched": 2}'
            result = _score_via_llm("some task")
        assert result is None

    def test_values_clamped_to_0_3(self) -> None:
        oob_json = (
            '{"files_touched": 5, "integrations": -1,'
            ' "security": 0, "scope": 3}'
        )
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = oob_json
            result = _score_via_llm("some task")
        assert result is not None
        assert result.files_touched == 3
        assert result.integrations == 0

    def test_truncates_long_prompt(self) -> None:
        small_json = (
            '{"files_touched": 1, "integrations": 0,'
            ' "security": 0, "scope": 1}'
        )
        long_desc = "x" * 5000
        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = small_json
            _score_via_llm(long_desc)
            # Verify the user prompt was truncated.
            call_kwargs = backend.one_shot.call_args.kwargs
            assert len(call_kwargs["user"]) == 2000


# ── Clamp helper ─────────────────────────────────────────────────


class TestClamp:
    def test_clamp_within_range(self) -> None:
        assert _clamp(2) == 2

    def test_clamp_below_min(self) -> None:
        assert _clamp(-5) == 0

    def test_clamp_above_max(self) -> None:
        assert _clamp(10) == 3


# ── Public score_complexity ──────────────────────────────────────


class TestScoreComplexity:
    """Tests for the unified score_complexity() with LLM + fallback."""

    def test_uses_llm_when_available(self) -> None:
        llm_score = ComplexityScore(files_touched=2, integrations=1, security=0, scope=3)
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=llm_score,
        ):
            result = score_complexity("build a new auth module")
        assert result.method == "llm"
        assert result.files_touched == 2

    def test_falls_back_to_heuristic_on_llm_failure(self) -> None:
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=None,
        ):
            result = score_complexity("fix a typo in the README", None)
        assert result.method == "heuristic"
        assert result.workflow in {"quick", "light"}

    def test_workflow_floor_upgrades(self) -> None:
        """Floor = standard, scorer says light → standard."""
        llm_score = ComplexityScore(files_touched=1, integrations=1, security=0, scope=0)
        assert llm_score.workflow in {"quick", "light"}  # sanity check
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=llm_score,
        ):
            result = score_complexity("small task", workflow_floor="standard")
        assert result.workflow == "standard"

    def test_workflow_floor_does_not_downgrade(self) -> None:
        """Floor = standard, scorer says full → full (not capped)."""
        llm_score = ComplexityScore(files_touched=3, integrations=3, security=3, scope=3)
        assert llm_score.workflow == "full"
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=llm_score,
        ):
            result = score_complexity("huge task", workflow_floor="standard")
        assert result.workflow == "full"

    def test_workflow_floor_none_no_effect(self) -> None:
        """No floor → scorer result is used as-is."""
        llm_score = ComplexityScore(files_touched=0, integrations=0, security=0, scope=0)
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=llm_score,
        ):
            result = score_complexity("tiny fix", workflow_floor=None)
        assert result.workflow == "quick"

    def test_workflow_floor_invalid_value_ignored(self) -> None:
        """Invalid floor value is silently ignored."""
        llm_score = ComplexityScore(files_touched=0, integrations=0, security=0, scope=0)
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=llm_score,
        ):
            result = score_complexity("tiny fix", workflow_floor="nonexistent")
        assert result.workflow == "quick"

    def test_all_dimensions_bounded_0_to_3(self) -> None:
        with patch(
            "devflow.integrations.complexity._score_via_llm",
            return_value=None,
        ):
            score = score_complexity(
                "Implement OAuth2 auth token system with database, redis, kafka, s3, "
                "webhook, graphql and billing payment crypto secret password RBAC permission "
                "ACL CORS CSRF. Redesign, rewrite, overhaul the entire new subsystem.",
                None,
            )
        assert 0 <= score.files_touched <= 3
        assert 0 <= score.integrations <= 3
        assert 0 <= score.security <= 3
        assert 0 <= score.scope <= 3

    @pytest.mark.parametrize(
        ("files_touched", "integrations", "security", "scope", "expected"),
        [
            (0, 0, 0, 0, "quick"),
            (1, 1, 0, 0, "quick"),
            (1, 1, 1, 0, "light"),
            (2, 1, 1, 1, "light"),
            (2, 2, 1, 1, "standard"),
            (2, 2, 2, 2, "standard"),
            (3, 2, 2, 2, "full"),
            (3, 3, 3, 3, "full"),
        ],
    )
    def test_workflow_mapping_boundaries(
        self,
        files_touched: int,
        integrations: int,
        security: int,
        scope: int,
        expected: str,
    ) -> None:
        score = ComplexityScore(
            files_touched=files_touched,
            integrations=integrations,
            security=security,
            scope=scope,
        )
        assert score.workflow == expected
