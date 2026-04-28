"""Tests for core/phase_outputs.py — structured review output parser."""

from __future__ import annotations

from devflow.core.phase_outputs import ReviewOutput, parse_review_output

# ── Fixtures: realistic reviewer outputs ───────────────────────────

FIXTURE_APPROVE_CLEAN = """\
The implementation looks solid. Good test coverage and clean separation.

Verdict: APPROVE

Blocking issues:
- None

Non-blocking notes:
- Consider extracting the retry logic into a helper for reuse
- Docstring missing on _handle_gate_result
"""

FIXTURE_REQUEST_CHANGES = """\
Several issues found during review.

Verdict: REQUEST_CHANGES

Blocking issues:
- src/devflow/core/config.py:42 — security — API key loaded without validation
- src/devflow/orchestration/build.py:87 — correctness — Missing null check on feature lookup

Non-blocking notes:
- Variable name `x` could be more descriptive
"""

FIXTURE_COMMENT = """\
Verdict: COMMENT

Blocking issues:
- None

Non-blocking notes:
- Good overall structure, consider adding docstrings
"""

FIXTURE_TOLERANT_EXTRA_SPACES = """\
  Verdict:   APPROVE

Blocking issues:
-  src/foo.py:10  —  style  —  missing type hint

Non-blocking notes:
-  minor naming issue
"""

FIXTURE_NO_VERDICT = """\
This looks good to me! LGTM.

No issues found, the code is clean and well-tested.
"""

FIXTURE_ALL_CATEGORIES = """\
Verdict: REQUEST_CHANGES

Blocking issues:
- src/auth.py:1 — security — SQL injection risk
- src/calc.py:2 — correctness — Off-by-one error
- tests/test_calc.py:3 — tests — Missing edge case test
- src/query.py:4 — perf — N+1 query in loop
- src/utils.py:5 — style — Inconsistent naming

Non-blocking notes:
- None
"""

FIXTURE_MULTILINE_ANALYSIS = """\
## Review: feat-042

### Architecture
- Layering: ✓ OK
- Responsibility: ✓ OK

The implementation follows the plan precisely. All tests pass.

Verdict: APPROVE

Blocking issues:
- None

Non-blocking notes:
- The new helper could also be used in build.py (not blocking)
"""

FIXTURE_DASH_VARIANTS = """\
Verdict: REQUEST_CHANGES

Blocking issues:
- src/a.py:10 — correctness — Missing check
- src/b.py:20 – style – Bad naming
- src/c.py:30 - perf - Slow loop

Non-blocking notes:
- Consider refactoring
"""

FIXTURE_APPROVE_WITH_BLOCKING = """\
Verdict: APPROVE

Blocking issues:
- src/x.py:1 — correctness — This should not be here with APPROVE

Non-blocking notes:
- None
"""

FIXTURE_EMPTY_SECTIONS = """\
Verdict: APPROVE

Blocking issues:

Non-blocking notes:
"""


class TestParseApprove:
    def test_clean_approve(self) -> None:
        result = parse_review_output(FIXTURE_APPROVE_CLEAN)
        assert result.verdict == "APPROVE"
        assert result.blocking_issues == []
        assert len(result.non_blocking_notes) == 2
        assert result.raw == FIXTURE_APPROVE_CLEAN

    def test_approve_with_multiline_analysis(self) -> None:
        result = parse_review_output(FIXTURE_MULTILINE_ANALYSIS)
        assert result.verdict == "APPROVE"


class TestParseRequestChanges:
    def test_request_changes_with_issues(self) -> None:
        result = parse_review_output(FIXTURE_REQUEST_CHANGES)
        assert result.verdict == "REQUEST_CHANGES"
        assert len(result.blocking_issues) == 2
        assert result.blocking_issues[0].file == "src/devflow/core/config.py"
        assert result.blocking_issues[0].line == "42"
        assert result.blocking_issues[0].category == "security"
        assert "API key" in result.blocking_issues[0].description
        assert result.blocking_issues[0].blocking is True

    def test_request_changes_notes(self) -> None:
        result = parse_review_output(FIXTURE_REQUEST_CHANGES)
        assert len(result.non_blocking_notes) == 1
        assert "Variable name" in result.non_blocking_notes[0]


class TestParseTolerant:
    def test_extra_spaces(self) -> None:
        result = parse_review_output(FIXTURE_TOLERANT_EXTRA_SPACES)
        assert result.verdict == "APPROVE"
        assert len(result.blocking_issues) == 1
        assert result.blocking_issues[0].file == "src/foo.py"
        assert result.blocking_issues[0].category == "style"

    def test_dash_variants(self) -> None:
        result = parse_review_output(FIXTURE_DASH_VARIANTS)
        assert result.verdict == "REQUEST_CHANGES"
        assert len(result.blocking_issues) >= 1
        assert result.blocking_issues[0].category == "correctness"

    def test_empty_sections(self) -> None:
        result = parse_review_output(FIXTURE_EMPTY_SECTIONS)
        assert result.verdict == "APPROVE"
        assert result.blocking_issues == []
        assert result.non_blocking_notes == []


class TestParseNonConforme:
    def test_no_verdict(self) -> None:
        result = parse_review_output(FIXTURE_NO_VERDICT)
        assert result.verdict == "UNKNOWN"
        assert result.raw == FIXTURE_NO_VERDICT

    def test_empty_string(self) -> None:
        result = parse_review_output("")
        assert result.verdict == "UNKNOWN"

    def test_garbage(self) -> None:
        result = parse_review_output("random text\nno structure\nat all")
        assert result.verdict == "UNKNOWN"


class TestParseCategories:
    def test_all_five_categories(self) -> None:
        result = parse_review_output(FIXTURE_ALL_CATEGORIES)
        categories = {i.category for i in result.blocking_issues}
        assert categories == {"security", "correctness", "tests", "perf", "style"}

    def test_category_count(self) -> None:
        result = parse_review_output(FIXTURE_ALL_CATEGORIES)
        assert len(result.blocking_issues) == 5


class TestParseComment:
    def test_comment_verdict(self) -> None:
        result = parse_review_output(FIXTURE_COMMENT)
        assert result.verdict == "COMMENT"


class TestParseEdgeCases:
    def test_approve_with_blocking_issues_still_parses(self) -> None:
        result = parse_review_output(FIXTURE_APPROVE_WITH_BLOCKING)
        assert result.verdict == "APPROVE"
        assert len(result.blocking_issues) == 1

    def test_case_insensitive_verdict(self) -> None:
        text = (
            "Verdict: approve\n\nBlocking issues:\n"
            "- None\n\nNon-blocking notes:\n- None"
        )
        result = parse_review_output(text)
        assert result.verdict == "APPROVE"

    def test_result_is_dataclass(self) -> None:
        result = parse_review_output(FIXTURE_APPROVE_CLEAN)
        assert isinstance(result, ReviewOutput)
