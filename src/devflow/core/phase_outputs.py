"""Structured output parsers for phase outputs (reviewer, etc.).

Strict-first, tolerant-fallback parsing: try the canonical format, then
degrade gracefully with warnings. Never crashes — always returns a valid
dataclass with ``raw`` preserving the original text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

_log = structlog.get_logger(__name__)

_VERDICT_RE = re.compile(
    r"^\s*Verdict:\s*(APPROVE|REQUEST_CHANGES|COMMENT)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ISSUE_RE = re.compile(r"^\s*-\s*(.+?):(\S+)\s*[—–-]\s*(\w+)\s*[—–-]\s*(.+)$")
_NOTE_RE = re.compile(r"^\s*-\s*(.+)$")


@dataclass
class ReviewIssue:
    file: str
    line: str
    category: str
    description: str
    blocking: bool


@dataclass
class ReviewOutput:
    verdict: str
    blocking_issues: list[ReviewIssue] = field(default_factory=list)
    non_blocking_notes: list[str] = field(default_factory=list)
    raw: str = ""


VALID_VERDICTS = frozenset({"APPROVE", "REQUEST_CHANGES", "COMMENT"})
VALID_CATEGORIES = frozenset({"security", "correctness", "tests", "perf", "style"})

REFORMAT_FEEDBACK = (
    "Ton output ne respecte pas le format attendu. Voici le format :\n\n"
    "Verdict: APPROVE | REQUEST_CHANGES | COMMENT\n\n"
    "Blocking issues:\n"
    "- <file>:<line> — <category> — <description>\n\n"
    "Non-blocking notes:\n"
    "- <description>\n\n"
    "Reformate ta review dans ce format."
)


def parse_review_output(text: str) -> ReviewOutput:
    """Parse structured reviewer output. Tolerant parser with warnings."""
    verdict_match = _VERDICT_RE.search(text)
    if not verdict_match:
        _log.warning("Reviewer output non-conforme: no Verdict: line found")
        return ReviewOutput(verdict="UNKNOWN", raw=text)

    verdict = verdict_match.group(1).upper()
    if verdict not in VALID_VERDICTS:
        _log.warning("Unknown verdict %r, treating as UNKNOWN", verdict)
        return ReviewOutput(verdict="UNKNOWN", raw=text)

    blocking_issues = _parse_issues(text, blocking=True)
    non_blocking_notes = _parse_notes(text)

    return ReviewOutput(
        verdict=verdict,
        blocking_issues=blocking_issues,
        non_blocking_notes=non_blocking_notes,
        raw=text,
    )


def _parse_issues(text: str, *, blocking: bool) -> list[ReviewIssue]:
    """Extract issue lines from the Blocking issues section."""
    section = _extract_section(text, "Blocking issues:")
    if not section:
        return []

    issues: list[ReviewIssue] = []
    for line in section.splitlines():
        m = _ISSUE_RE.match(line)
        if m:
            category = m.group(3).lower()
            if category not in VALID_CATEGORIES:
                _log.warning("Unknown review category %r, keeping as-is", category)
            issues.append(ReviewIssue(
                file=m.group(1).strip(),
                line=m.group(2).strip(),
                category=category,
                description=m.group(4).strip(),
                blocking=blocking,
            ))
    return issues


def _parse_notes(text: str) -> list[str]:
    """Extract note lines from the Non-blocking notes section."""
    section = _extract_section(text, "Non-blocking notes:")
    if not section:
        return []

    notes: list[str] = []
    for line in section.splitlines():
        m = _NOTE_RE.match(line)
        if m:
            notes.append(m.group(1).strip())
    return notes


def _extract_section(text: str, header: str) -> str:
    """Extract content between a section header and the next section or end."""
    idx = text.find(header)
    if idx == -1:
        lower_header = header.lower()
        lower_text = text.lower()
        idx = lower_text.find(lower_header)
        if idx == -1:
            return ""

    start = idx + len(header)
    remaining = text[start:]

    end_markers = ["Verdict:", "Blocking issues:", "Non-blocking notes:"]
    end_markers = [m for m in end_markers if m.lower() != header.lower()]

    end = len(remaining)
    for marker in end_markers:
        pos = remaining.find(marker)
        if pos == -1:
            pos = remaining.lower().find(marker.lower())
        if pos != -1 and pos < end:
            end = pos

    return remaining[:end]
