"""Diff-min anti-loop — abort retries that make no progress.

Compares consecutive retry diffs via SequenceMatcher. When the
similarity exceeds the configured threshold (default 0.95), the retry
is aborted to avoid burning tokens on a loop that isn't converging.
"""

from __future__ import annotations

import difflib

import structlog

_log = structlog.get_logger(__name__)


def diff_similarity(diff_a: str, diff_b: str) -> float:
    """Return similarity ratio (0.0–1.0) between two diffs."""
    if not diff_a and not diff_b:
        return 1.0
    if not diff_a or not diff_b:
        return 0.0
    return difflib.SequenceMatcher(None, diff_a, diff_b).ratio()


def should_abort_retry(
    previous_diff: str,
    current_diff: str,
    threshold: float = 0.95,
) -> bool:
    """Return True when the retry diff is too similar to the previous one."""
    sim = diff_similarity(previous_diff, current_diff)
    if sim >= threshold:
        _log.warning(
            "Retry aborted — diff similarity %.0f%%, retry is not making progress.",
            sim * 100,
        )
        return True
    return False
