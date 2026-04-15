"""Complexity scoring — analyse task description and codebase to pick a workflow."""

from __future__ import annotations

import re
from pathlib import Path

from devflow.core.models import ComplexityScore
from devflow.integrations.detect import _walk

# Security-sensitive path/term patterns (shared with orchestration.build).
CRITICAL_PATH_PATTERNS: tuple[str, ...] = (
    "auth", "secret", "token", "crypto", "payment", "billing", "password",
)

# Additional security terms not covered by CRITICAL_PATH_PATTERNS.
_SECURITY_EXTRA: tuple[str, ...] = ("rbac", "permission", "acl", "privilege", "cors", "csrf")

# External integration keywords.
_INTEGRATION_KEYWORDS: tuple[str, ...] = (
    "api", "database", "webhook", "queue", "oauth", "third-party", "redis",
    "postgres", "mysql", "mongodb", "elasticsearch", "kafka", "rabbitmq",
    "s3", "storage", "email", "smtp", "sms", "twilio", "stripe", "firebase",
    "graphql", "grpc", "rest",
)

# Action verbs that imply wide scope (each hit adds weight).
_HIGH_SCOPE_VERBS: tuple[str, ...] = (
    "create", "redesign", "migrate", "rewrite", "refactor", "build",
    "add module", "new subsystem", "overhaul", "implement", "new feature",
)
_LOW_SCOPE_VERBS: tuple[str, ...] = (
    "fix", "tweak", "rename", "update", "adjust", "clean", "remove",
    "typo", "comment", "bump", "minor",
)

# Source file extensions to count when measuring project size.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".php", ".go", ".rs", ".java", ".kt"}
)


def _count_source_files(base: Path) -> int:
    """Count source files in *base*, ignoring build/cache directories."""
    return sum(1 for f in _walk(base) if f.suffix in _SOURCE_EXTENSIONS)


def _score_files_touched(description: str, base: Path | None) -> int:
    """Score 0-3: how many files are likely to be touched."""
    desc = description.lower()

    # Wide-scope keywords → at least 2.
    wide_hints = ("new module", "multiple files", "new subsystem", "rewrite", "overhaul")
    if any(h in desc for h in wide_hints):
        base_score = 3 if "new subsystem" in desc or "overhaul" in desc else 2
    elif any(v in desc for v in ("refactor", "add module", "new feature", "implement")):
        base_score = 2
    elif any(v in desc for v in ("add field", "add column", "add endpoint", "add method")):
        base_score = 1
    else:
        base_score = 1

    # Project size cap: small projects (< 20 source files) cap score at 1.
    if base is not None and base.exists():
        n_files = _count_source_files(base)
        if n_files < 20:
            base_score = min(base_score, 1)

    return min(base_score, 3)


def _score_integrations(description: str) -> int:
    """Score 0-3: number of external systems mentioned in the description."""
    desc = description.lower()
    hits = sum(1 for kw in _INTEGRATION_KEYWORDS if re.search(r"\b" + re.escape(kw) + r"\b", desc))
    if hits == 0:
        return 0
    if hits == 1:
        return 1
    if hits <= 3:
        return 2
    return 3


def _score_security(description: str) -> int:
    """Score 0-3: security-sensitive surface area in the description."""
    desc = description.lower()
    all_patterns = CRITICAL_PATH_PATTERNS + _SECURITY_EXTRA
    hits = sum(1 for pat in all_patterns if pat in desc)
    if hits == 0:
        return 0
    if hits == 1:
        return 1
    if hits <= 3:
        return 2
    return 3


def _score_scope(description: str) -> int:
    """Score 0-3: breadth of the change based on verbs and description length."""
    desc = description.lower()

    high_hits = sum(1 for v in _HIGH_SCOPE_VERBS if v in desc)
    low_hits = sum(1 for v in _LOW_SCOPE_VERBS if v in desc)

    # Net verb score.
    net = high_hits - low_hits

    # Description length bonus: longer descriptions imply broader scope.
    words = len(description.split())
    length_bonus = 0
    if words >= 30:
        length_bonus = 2
    elif words >= 15:
        length_bonus = 1

    raw = net + length_bonus
    return max(0, min(raw, 3))


def score_complexity(description: str, base: Path | None = None) -> ComplexityScore:
    """Analyse *description* (and optionally the project at *base*) to produce
    a :class:`ComplexityScore` that maps to a recommended workflow.

    Args:
        description: The feature description string.
        base: Optional project root used for file-count heuristics.

    Returns:
        A :class:`ComplexityScore` with individual dimension scores and a
        ``workflow`` property (``"quick"`` / ``"light"`` / ``"standard"`` / ``"full"``).
    """
    return ComplexityScore(
        files_touched=_score_files_touched(description, base),
        integrations=_score_integrations(description),
        security=_score_security(description),
        scope=_score_scope(description),
    )
