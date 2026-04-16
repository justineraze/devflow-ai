"""Tests for devflow.integrations.complexity — scoring engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.integrations.complexity import (
    CRITICAL_PATH_PATTERNS,
    _score_files_touched,
    _score_integrations,
    _score_scope,
    _score_security,
    score_complexity,
)


class TestCriticalPathPatterns:
    def test_contains_expected_patterns(self) -> None:
        for pat in ("auth", "secret", "token", "crypto", "payment", "billing", "password"):
            assert pat in CRITICAL_PATH_PATTERNS


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
        """Projects with < 20 source files cap files_touched at 1."""
        # Create 5 source files.
        for i in range(5):
            (tmp_path / f"module_{i}.py").write_text(f"# module {i}")
        score = _score_files_touched("add new module for reporting", tmp_path)
        assert score == 1

    def test_large_project_not_capped(self, tmp_path: Path) -> None:
        """Projects with >= 20 source files allow higher scores."""
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
        # 3 hits (payment, billing, crypto) → score 2 per the <=3 bucket
        assert _score_security("handle payment and billing with crypto") == 2

    def test_four_security_patterns_scores_max(self) -> None:
        # 4+ hits → score 3
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
        # Length bonus should push score up even without explicit verbs.
        assert score >= 1

    def test_low_scope_verbs_decrease_score(self) -> None:
        score = _score_scope("minor fix and rename the variable")
        assert score <= 1


class TestScoreComplexity:
    def test_trivial_description_gives_quick(self) -> None:
        score = score_complexity("fix a typo in the README", None)
        assert score.workflow in {"quick", "light"}

    def test_complex_description_gives_standard_or_full(self) -> None:
        score = score_complexity(
            "Implement OAuth2 authentication with JWT tokens and RBAC permission system "
            "integrated with the database and Redis cache. Rewrite the auth module.",
            None,
        )
        assert score.workflow in {"standard", "full"}

    def test_returns_complexity_score_model(self) -> None:
        from devflow.core.models import ComplexityScore

        score = score_complexity("add a field", None)
        assert isinstance(score, ComplexityScore)
        assert 0 <= score.total <= 12

    def test_all_dimensions_bounded_0_to_3(self) -> None:
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

    def test_with_project_base(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("# app")
        score = score_complexity("fix bug in parser", tmp_path)
        assert score.workflow in {"quick", "light"}

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
        from devflow.core.models import ComplexityScore

        score = ComplexityScore(
            files_touched=files_touched,
            integrations=integrations,
            security=security,
            scope=scope,
        )
        assert score.workflow == expected
