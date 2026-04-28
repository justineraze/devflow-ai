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
        long_desc = " ".join(["word"] * 60)
        score = _score_scope(long_desc)
        assert score >= 1

    def test_short_description_no_bonus(self) -> None:
        # 30 words used to bump scope to +2 — empirically too aggressive.
        score = _score_scope(" ".join(["word"] * 30))
        assert score == 0

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
            # Bornes (1, 4, 7, 12): empirically tuned 2026-04-26 to push
            # multi-file work out of "light" without inflating trivial fixes.
            (0, 0, 0, 0, "quick"),       # total=0
            (1, 0, 0, 0, "quick"),       # total=1
            (1, 1, 0, 0, "light"),       # total=2
            (1, 1, 1, 0, "light"),       # total=3
            (2, 1, 1, 0, "light"),       # total=4 (light upper bound)
            (2, 1, 1, 1, "standard"),    # total=5
            (2, 2, 1, 1, "standard"),    # total=6
            (2, 2, 2, 1, "standard"),    # total=7 (standard upper bound)
            (2, 2, 2, 2, "full"),        # total=8
            (3, 2, 2, 2, "full"),        # total=9
            (3, 3, 3, 3, "full"),        # total=12
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


# ── Scope: word-boundary (anti-substring bug) ────────────────────


class TestScopeWordBoundary:
    """The previous heuristic used `if v in desc.lower()` which caused
    false positives on identifier names ("build" in "BuildMetrics").
    Word-boundary regex prevents this.
    """

    def test_build_in_camelcase_identifier_does_not_match(self) -> None:
        # "BuildMetrics" / "BuildTotals" must NOT trigger the "build"
        # high-scope verb. Only ~10 words → no length bonus either.
        score = _score_scope("Add docs about BuildMetrics and BuildTotals classes")
        assert score == 0

    def test_create_in_creator_substring_does_not_match(self) -> None:
        # "creator" should not match the verb "create".
        score = _score_scope("Document the FeatureCreator helper class")
        assert score == 0

    def test_implement_word_alone_still_matches(self) -> None:
        # Sanity check: real verb usage still scores.
        score = _score_scope("Implement a small helper function")
        assert score >= 1


# ── Scope: doc-only detector ─────────────────────────────────────


class TestDocOnlyDetector:
    """Documentation-only descriptions should cap at scope=1, even if
    verbose enough to trigger the length bonus.
    """

    def test_readme_caps_long_doc(self) -> None:
        long_doc = (
            "Update the README with a comprehensive section explaining "
            "every public class and helper, including all examples, "
            "edge cases, and the rationale behind every design choice. "
            "No code change needed. " + "filler word " * 30
        )
        score = _score_scope(long_doc)
        assert score <= 1

    def test_claude_md_doc_only(self) -> None:
        desc = (
            "Add a short section in CLAUDE.md explaining the Pydantic "
            "vs dataclass convention. One paragraph. Do not change any code."
        )
        score = _score_scope(desc)
        assert score <= 1

    def test_doc_with_high_verb_not_capped(self) -> None:
        # If the desc mentions a real refactor verb, doc-only cap doesn't apply.
        desc = "Rewrite the README with a fresh structure across all sections."
        score = _score_scope(desc)
        assert score >= 1


# ── files_touched: structural signals (bullets/paths) ────────────


class TestFilesTouchedStructural:
    """The previous heuristic only used keyword triggers. New logic
    also reads bullet lists and explicit file-path mentions.
    """

    def test_three_paths_score_at_least_two(self) -> None:
        desc = "Add a CLI flag --json to status.py, check.py, and metrics.py"
        score = _score_files_touched(desc, None)
        assert score >= 2

    def test_four_bulleted_items_score_at_least_two(self) -> None:
        desc = (
            "Test these modules:\n"
            "- foo\n"
            "- bar\n"
            "- baz\n"
            "- qux\n"
        )
        score = _score_files_touched(desc, None)
        assert score >= 2

    def test_six_paths_score_three(self) -> None:
        desc = (
            "Refactor build.py into modules: build_loop.py, do_loop.py, "
            "retry_policy.py, review_cycle.py, finalize.py"
        )
        score = _score_files_touched(desc, None)
        assert score == 3

    def test_no_structural_signal_keyword_still_works(self) -> None:
        # Pure keyword path still works when no bullets/paths present.
        score = _score_files_touched("overhaul the authentication layer", None)
        assert score == 3


# ── 12 calibrated fixtures (heuristic) ────────────────────────────

_FIXTURES: tuple[tuple[str, str, str], ...] = (
    # Trivial → quick
    ("Q1", "quick", "Fix typo in README"),
    ("Q2", "quick", "Update CHANGELOG with v2.1.0 release notes"),
    ("Q3", "quick", "Bump ruff to 0.7.0 in pyproject.toml"),
    ("Q4", "quick",
     "Add a short section in CLAUDE.md explaining the Pydantic vs dataclass "
     "convention. One paragraph, 3-4 lines max. Do not change any code."),
    # Single feature → light
    ("L1", "light",
     "Implement a retry helper in core/retry.py with exponential backoff. "
     "Add unit tests."),
    ("L2", "light",
     "Refactor logger.py to use structlog. Update the import sites."),
    ("L3", "light",
     "Add a CLI flag --json to status.py, check.py, and metrics.py commands"),
    ("L4", "light",
     "Add a webhook handler in integrations/webhook.py with HMAC signature "
     "validation and retry queue"),
    # Multi-module work → standard
    ("S1", "standard",
     "Add tests for 4 modules: phase_exec.py, gate/checks.py, gate/report.py, "
     "gate/secrets.py. Mirror src/ structure in tests/."),
    ("S2", "standard",
     "Refactor build.py into 5 modules: build_loop.py, do_loop.py, "
     "retry_policy.py, review_cycle.py, finalize.py. Extract retry helpers. "
     "Behavior unchanged."),
    ("S3", "standard",
     "Implement a Linear webhook handler to sync issue status both ways. "
     "New HTTP endpoint, Pydantic models, retry queue with exponential "
     "backoff, full test suite."),
    # New subsystem with critical security → full
    ("F1", "full",
     "Implement OAuth SSO with Google and GitHub providers. "
     "Touches auth/login.py, auth/jwt.py, auth/session.py, auth/rbac.py "
     "and models/user.py. Includes user migration, JWT, session management, "
     "RBAC roles, full test suite."),
)


class TestComplexityFixtures:
    """The 12 calibrated fixtures — single source of truth for the
    expected workflow distribution. Heuristic-only (no LLM).
    """

    @pytest.mark.parametrize(("fid", "expected", "desc"), _FIXTURES)
    def test_heuristic_workflow(self, fid: str, expected: str, desc: str) -> None:
        score = _score_heuristic(desc, None)
        assert score.workflow == expected, (
            f"[{fid}] expected {expected!r}, got {score.workflow!r} "
            f"(dims: f={score.files_touched} i={score.integrations} "
            f"s={score.security} sc={score.scope}, total={score.total})"
        )

    def test_distribution_is_plausible(self) -> None:
        # No bucket should hold more than 50% of fixtures (the original
        # bug was 67% landing in light/quick).
        from collections import Counter
        results = Counter(_score_heuristic(desc, None).workflow for _, _, desc in _FIXTURES)
        n = len(_FIXTURES)
        assert max(results.values()) <= n // 2 + 1, (
            f"distribution skewed: {dict(results)} (total={n})"
        )


# ── LLM calibration anchors (mocked) ──────────────────────────────


class TestLLMCalibration:
    """When the LLM returns the calibration anchor values from the
    prompt, the resolved workflow must match the anchor's tier.
    """

    @pytest.mark.parametrize(
        ("dims", "expected"),
        [
            # Anchor 1 — quick (total=0)
            ({"files_touched": 0, "integrations": 0, "security": 0, "scope": 0}, "quick"),
            # Anchor 2 — light (total=2)
            ({"files_touched": 1, "integrations": 0, "security": 0, "scope": 1}, "light"),
            # Anchor 3 — standard (total=5: broad refactor of multi-module)
            ({"files_touched": 2, "integrations": 0, "security": 0, "scope": 3}, "standard"),
            # Anchor 4 — full (total=10: critical security new subsystem)
            ({"files_touched": 2, "integrations": 2, "security": 3, "scope": 3}, "full"),
        ],
    )
    def test_anchor_workflows(self, dims: dict[str, int], expected: str) -> None:
        import json as _json

        with patch("devflow.integrations.complexity.get_backend") as mock_be:
            backend = mock_be.return_value
            backend.model_name.return_value = "haiku"
            backend.one_shot.return_value = _json.dumps(dims)
            result = score_complexity("any task")
        assert result.workflow == expected
        assert result.method == "llm"
