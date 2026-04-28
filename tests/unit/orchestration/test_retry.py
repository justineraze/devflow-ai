"""Tests for orchestration/retry.py — diff-min anti-loop."""

from __future__ import annotations

from devflow.orchestration.retry import diff_similarity, should_abort_retry


class TestDiffSimilarity:
    def test_identical_diffs(self) -> None:
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,3 @@\n-old\n+new"
        assert diff_similarity(diff, diff) == 1.0

    def test_completely_different_diffs(self) -> None:
        diff_a = "removed all the old authentication code and replaced with oauth"
        diff_b = "added new payment processing module with stripe integration xyz"
        sim = diff_similarity(diff_a, diff_b)
        assert sim < 0.5

    def test_empty_both(self) -> None:
        assert diff_similarity("", "") == 1.0

    def test_empty_one(self) -> None:
        assert diff_similarity("", "some diff") == 0.0
        assert diff_similarity("some diff", "") == 0.0

    def test_similar_diffs(self) -> None:
        diff_a = "--- a/foo.py\n+++ b/foo.py\n-x = 1\n+x = 2"
        diff_b = "--- a/foo.py\n+++ b/foo.py\n-x = 1\n+x = 3"
        sim = diff_similarity(diff_a, diff_b)
        assert 0.5 < sim < 1.0


class TestShouldAbortRetry:
    def test_identical_aborts(self) -> None:
        diff = "some diff content"
        assert should_abort_retry(diff, diff) is True

    def test_different_continues(self) -> None:
        assert should_abort_retry("abc", "xyz completely different") is False

    def test_threshold_default(self) -> None:
        diff = "x" * 100
        slightly_different = "x" * 96 + "yyyy"
        sim = diff_similarity(diff, slightly_different)
        result = should_abort_retry(diff, slightly_different)
        if sim >= 0.95:
            assert result is True
        else:
            assert result is False

    def test_threshold_configurable(self) -> None:
        diff_a = "abc"
        diff_b = "abd"
        assert should_abort_retry(diff_a, diff_b, threshold=0.5) is True
        assert should_abort_retry(diff_a, diff_b, threshold=0.99) is False

    def test_empty_diffs_abort(self) -> None:
        assert should_abort_retry("", "") is True
