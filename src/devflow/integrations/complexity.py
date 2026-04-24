"""Complexity scoring — analyse task description to pick a workflow.

Primary scorer uses the backend LLM (Haiku-tier one-shot) to evaluate
task complexity across four dimensions.  Falls back to the keyword-based
heuristic if the LLM call fails for any reason.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from devflow.core.backend import ModelTier, get_backend
from devflow.core.complexity import ComplexityScore
from devflow.core.security import CRITICAL_PATH_PATTERNS
from devflow.integrations.detect import walk_files

log = logging.getLogger(__name__)

# ── LLM scorer ────────────────────────────────────────────────────

_SCORER_SYSTEM = """\
You are a task complexity scorer for a software build system.
Given a development task description, score its complexity on 4 dimensions (each 0-3):

- files_touched: how many files will be created or modified
  0 = 1 file, 1 = 2-3 files, 2 = 4-8 files, 3 = 9+ files
- integrations: external systems involved
  0 = none, 1 = 1 system, 2 = 2-3 systems, 3 = 4+ systems
- security: security-sensitive surface area
  0 = none, 1 = minor, 2 = auth/tokens/crypto, 3 = critical
- scope: breadth of change
  0 = tweak, 1 = small feature, 2 = new module, 3 = multi-module

Respond with ONLY a JSON object, no explanation:
{"files_touched": N, "integrations": N, "security": N, "scope": N}"""

# Truncate user prompt to keep cost low (~$0.001 per call).
_MAX_PROMPT_CHARS = 2000

# LLM timeout — fast enough to not stall the build.
_LLM_TIMEOUT = 15


def _score_via_llm(description: str) -> ComplexityScore | None:
    """Score complexity via a one-shot LLM call.  Returns ``None`` on failure."""
    backend = get_backend()
    model = backend.model_name(ModelTier.FAST)
    user_prompt = description[:_MAX_PROMPT_CHARS]

    try:
        raw = backend.one_shot(
            system=_SCORER_SYSTEM,
            user=user_prompt,
            model=model,
            timeout=_LLM_TIMEOUT,
        )
    except (OSError, TimeoutError, RuntimeError):
        log.debug("LLM complexity scorer: backend call failed", exc_info=True)
        return None

    if not raw:
        return None

    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        log.debug("LLM complexity scorer: invalid JSON response: %s", raw[:200])
        return None

    try:
        return ComplexityScore(
            files_touched=_clamp(data["files_touched"]),
            integrations=_clamp(data["integrations"]),
            security=_clamp(data["security"]),
            scope=_clamp(data["scope"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        log.debug("LLM complexity scorer: bad payload: %s (%s)", data, exc)
        return None


def _clamp(value: int | float | str, lo: int = 0, hi: int = 3) -> int:
    """Clamp an integer value to [lo, hi], raising on non-int."""
    return max(lo, min(int(value), hi))


# ── Heuristic scorer (fallback) ──────────────────────────────────

# Additional security terms not covered by CRITICAL_PATH_PATTERNS.
_SECURITY_EXTRA: frozenset[str] = frozenset(
    {"rbac", "permission", "acl", "privilege", "cors", "csrf"}
)

# External integration keywords.
_INTEGRATION_KEYWORDS: frozenset[str] = frozenset({
    "api", "database", "webhook", "queue", "oauth", "third-party", "redis",
    "postgres", "mysql", "mongodb", "elasticsearch", "kafka", "rabbitmq",
    "s3", "storage", "email", "smtp", "sms", "twilio", "stripe", "firebase",
    "graphql", "grpc", "rest",
})

# Action verbs that imply wide scope (each hit adds weight).
_HIGH_SCOPE_VERBS: frozenset[str] = frozenset({
    "create", "redesign", "migrate", "rewrite", "refactor", "build",
    "add module", "new subsystem", "overhaul", "implement", "new feature",
})
_LOW_SCOPE_VERBS: frozenset[str] = frozenset({
    "fix", "tweak", "rename", "update", "adjust", "clean", "remove",
    "typo", "comment", "bump", "minor",
})

# Source file extensions to count when measuring project size.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".php", ".go", ".rs", ".java", ".kt"}
)


def _count_source_files(base: Path) -> int:
    """Count source files in *base*, ignoring build/cache directories."""
    return sum(1 for f in walk_files(base) if f.suffix in _SOURCE_EXTENSIONS)


def _score_files_touched(description: str, base: Path | None) -> int:
    """Score 0-3: how many files are likely to be touched."""
    desc = description.lower()

    # Wide-scope keywords → at least 2.
    wide_hints = ("new module", "multiple files", "new subsystem", "rewrite", "overhaul")
    if any(h in desc for h in wide_hints):
        base_score = 3 if "new subsystem" in desc or "overhaul" in desc else 2
    elif any(v in desc for v in ("refactor", "add module", "new feature", "implement")):
        base_score = 2
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
    all_patterns = frozenset(CRITICAL_PATH_PATTERNS) | _SECURITY_EXTRA
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

    net = high_hits - low_hits

    words = len(description.split())
    length_bonus = 0
    if words >= 30:
        length_bonus = 2
    elif words >= 15:
        length_bonus = 1

    raw = net + length_bonus
    return max(0, min(raw, 3))


def _score_heuristic(description: str, base: Path | None = None) -> ComplexityScore:
    """Keyword-based heuristic scorer (original algorithm, kept as fallback)."""
    return ComplexityScore(
        files_touched=_score_files_touched(description, base),
        integrations=_score_integrations(description),
        security=_score_security(description),
        scope=_score_scope(description),
    )


# ── Public API ────────────────────────────────────────────────────

# Workflow ordering for floor comparison.
_WORKFLOW_RANK: dict[str, int] = {
    "quick": 0,
    "light": 1,
    "standard": 2,
    "full": 3,
}


def score_complexity(
    description: str,
    base: Path | None = None,
    *,
    workflow_floor: str | None = None,
) -> ComplexityScore:
    """Score task complexity via LLM, falling back to keyword heuristics.

    Args:
        description: The feature description string.
        base: Optional project root used for file-count heuristics (fallback only).
        workflow_floor: Minimum workflow level (from config.workflow).
            The scorer can upgrade but never downgrade below this floor.

    Returns:
        A :class:`ComplexityScore` with a ``method`` annotation indicating
        whether the score came from the LLM or the heuristic fallback.
    """
    llm_score = _score_via_llm(description)

    if llm_score is not None:
        score = llm_score
        score.method = "llm"
    else:
        score = _score_heuristic(description, base)
        score.method = "heuristic"

    # Apply workflow floor: if the scored workflow ranks below the floor,
    # override the workflow field to the floor value.
    if workflow_floor and workflow_floor in _WORKFLOW_RANK:
        scored_rank = _WORKFLOW_RANK[score.workflow]
        floor_rank = _WORKFLOW_RANK[workflow_floor]
        if scored_rank < floor_rank:
            score = score.model_copy(update={"workflow": workflow_floor})

    return score
