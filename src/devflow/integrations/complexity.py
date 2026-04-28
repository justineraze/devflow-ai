"""Complexity scoring — analyse task description to pick a workflow.

Primary scorer uses the backend LLM (Haiku-tier one-shot) to evaluate
task complexity across four dimensions.  Falls back to the keyword-based
heuristic if the LLM call fails for any reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from devflow.core.backend import ModelTier, get_backend
from devflow.core.complexity import ComplexityScore
from devflow.integrations.detect import walk_files

log = structlog.get_logger(__name__)

# ── LLM scorer ────────────────────────────────────────────────────

_SCORER_SYSTEM = """\
You are a task complexity scorer for a software build system.
Score the task complexity on 4 dimensions (each 0-3).

CALIBRATION ANCHORS — use these as reference points:

(1) "Fix typo in README"
    -> {"files_touched": 0, "integrations": 0, "security": 0, "scope": 0}

(2) "Add a CLI --json flag to status, check, and metrics commands"
    -> {"files_touched": 1, "integrations": 0, "security": 0, "scope": 1}
    # 3 commands touched, narrow scope

(3) "Refactor build.py into 5 modules: build_loop, do_loop, retry_policy,
     review_cycle, finalize. Extract retry helpers, behavior unchanged."
    -> {"files_touched": 2, "integrations": 0, "security": 0, "scope": 3}
    # 5 files = files_touched=2 (4-8); broad multi-module refactor -> scope=3

(4) "Implement OAuth2 SSO with Google + GitHub. JWT, sessions, RBAC, full tests."
    -> {"files_touched": 2, "integrations": 2, "security": 3, "scope": 3}
    # auth + 2 providers + payment-grade security

DIMENSIONS:

- files_touched (count concrete files mentioned, bulleted, or implied)
  0 = 1 file or unclear; 1 = 2-3 files; 2 = 4-8 files; 3 = 9+ files
  RULE: when description lists multiple modules/paths/bullets, prefer 2 over 1.

- integrations (external systems the code talks to)
  0 = none; 1 = 1; 2 = 2-3; 3 = 4+

- security (the task MODIFIES auth/crypto/sessions/payment code)
  0 = none, OR description only mentions security TERMS in jargon
       (e.g. "BuildMetrics", "TokenUsage" as a class name) -> score 0
  1 = touches input validation or non-critical access
  2 = modifies auth/tokens/sessions/crypto
  3 = critical: payment, RBAC engine, password handling, full SSO
  RULE: a doc that NAMES classes like "TokenUsage" is NOT security work.

- scope (BREADTH of change, not description length)
  0 = trivial tweak (typo, comment, version bump)
  1 = small change in one place
  2 = touches multiple modules, adds a new module
  3 = multi-module rewrite, new subsystem, broad refactor
  RULE: a verbose description != broad scope. Documentation tasks score 0-1.

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

# Security keywords — listed explicitly with their common derivations so we
# can score on word boundaries without false positives ("author" must not
# match "auth", "secretary" must not match "secret"). Path-style stems live
# in ``CRITICAL_PATH_PATTERNS`` because phase_artifacts substring-matches
# them against file paths, which is a different problem than scoring a
# free-text description.
_SECURITY_KEYWORDS: frozenset[str] = frozenset({
    # Authentication / authorization.
    "auth", "authentication", "authorization",
    "authenticate", "authorize", "authn", "authz",
    # Secrets / credentials.
    "secret", "secrets", "credential", "credentials",
    "password", "passwords", "passwd",
    # Tokens / sessions.
    "token", "tokens", "session", "sessions",
    # Crypto.
    "crypto", "cryptography", "encryption", "decryption",
    "hash", "hashing",
    # Money flows (CRITICAL_PATH_PATTERNS path stems).
    "payment", "payments", "billing",
    # Access control.
    "rbac", "permission", "permissions", "acl",
    "privilege", "privileges", "cors", "csrf",
    # SSO / JWT — added 2026-04-26 after audit (OAuth-style descriptions
    # were undershooting on security because individual keywords didn't
    # cover the modern auth stack).
    "sso", "jwt",
})

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

# Structural signals — file paths and bullet lists embedded in the
# description. These let the scorer detect multi-file work even when
# the prose lacks high-scope verbs ("refactor", "new module"…).
_PATH_PATTERN = re.compile(
    r"\b[\w/]+\.(?:py|ts|tsx|js|jsx|md|yaml|yml|json|toml|sh|php|go|rs|java|kt)\b"
)
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+", re.MULTILINE)

# Documentation-only signals. When any of these match AND no high-scope
# verb is present, the task is treated as a doc edit and `_score_scope`
# caps at 1 — verbose doc descriptions used to inflate scope via the
# length bonus (audit 2026-04-26).
_DOC_ONLY_PATTERNS: tuple[str, ...] = (
    r"\bREADME\b",
    r"\bCLAUDE\.md\b",
    r"\bCHANGELOG\b",
    r"\b(?:do not|don'?t)\s+change\s+(?:any\s+)?code\b",
    r"\bno\s+code\s+change(?:s)?\b",
    r"\bdocumentation\s+only\b",
)


def _count_source_files(base: Path) -> int:
    """Count source files in *base*, ignoring build/cache directories."""
    return sum(1 for f in walk_files(base) if f.suffix in _SOURCE_EXTENSIONS)


def _count_paths(description: str) -> int:
    """Count distinct file paths mentioned in the description."""
    return len(set(_PATH_PATTERN.findall(description)))


def _count_bullets(description: str) -> int:
    """Count list items (`- `, `* `, `1.`, `1)`) in the description."""
    return len(_BULLET_PATTERN.findall(description))


def _is_doc_only(description: str) -> bool:
    """Return True if the description signals a doc-only task."""
    return any(re.search(pat, description, re.IGNORECASE) for pat in _DOC_ONLY_PATTERNS)


def _score_files_touched(description: str, base: Path | None) -> int:
    """Score 0-3: how many files are likely to be touched.

    Reads structural signals first (bullet lists, file-path mentions),
    then falls back to keyword heuristics. The structural pass catches
    descriptions that enumerate concrete files without using verbs like
    "refactor" or "new module".
    """
    desc = description.lower()

    # Structural signal: paths and bullets reveal file count directly.
    paths = _count_paths(description)
    bullets = _count_bullets(description)
    if paths >= 6 or bullets >= 8:
        structural_score = 3
    elif paths >= 3 or bullets >= 4:
        structural_score = 2
    elif paths >= 2 or bullets >= 2:
        structural_score = 1
    else:
        structural_score = 0

    # Keyword fallback (legacy path).
    wide_hints = ("new module", "multiple files", "new subsystem", "rewrite", "overhaul")
    if any(h in desc for h in wide_hints):
        keyword_score = 3 if "new subsystem" in desc or "overhaul" in desc else 2
    elif any(v in desc for v in ("refactor", "add module", "new feature", "implement")):
        keyword_score = 2
    else:
        keyword_score = 1

    base_score = max(structural_score, keyword_score)

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
    """Score 0-3: security-sensitive surface area in the description.

    Matches each keyword as a whole word (``\\b...\\b``) so descriptions
    that mention ``author`` or ``secretary`` aren't flagged as
    auth/secret work. Common derivations (``authentication``, ``tokens``…)
    are listed explicitly in :data:`_SECURITY_KEYWORDS`.
    """
    desc = description.lower()
    hits = sum(
        1 for pat in _SECURITY_KEYWORDS
        if re.search(r"\b" + re.escape(pat) + r"\b", desc)
    )
    if hits == 0:
        return 0
    if hits == 1:
        return 1
    if hits <= 3:
        return 2
    return 3


def _score_scope(description: str) -> int:
    """Score 0-3: breadth of the change.

    Uses word-boundary regex (not substring) to avoid false positives
    on identifier names — "build" must not match "BuildMetrics", "create"
    must not match "FeatureCreator". Multi-word verbs like "new module"
    are matched as whole phrases.

    The length bonus only kicks in for genuinely long descriptions
    (50+ words). Verbose doc descriptions are capped at 1 via the
    doc-only signal so they can't inflate scope on word count alone.
    Multi-file structural signals (≥4 paths or ≥8 bullets) lift scope
    by one tier when the prose lacks high-scope verbs.
    """
    desc = description.lower()

    high_hits = sum(
        1 for v in _HIGH_SCOPE_VERBS
        if re.search(r"\b" + re.escape(v) + r"\b", desc)
    )
    low_hits = sum(
        1 for v in _LOW_SCOPE_VERBS
        if re.search(r"\b" + re.escape(v) + r"\b", desc)
    )
    net = high_hits - low_hits

    words = len(description.split())
    length_bonus = 0
    if words >= 100:
        length_bonus = 2
    elif words >= 50:
        length_bonus = 1

    score = max(0, min(net + length_bonus, 3))

    # Structural boost: many distinct paths/bullets imply breadth even
    # if the prose lacks high-scope verbs (e.g. "Add tests for foo.py,
    # bar.py, baz.py, qux.py" doesn't say "refactor" but is multi-module).
    paths = _count_paths(description)
    bullets = _count_bullets(description)
    if paths >= 4 or bullets >= 8:
        score = max(score, 2)
    elif paths >= 3 or bullets >= 4:
        score = max(score, 1)

    # Documentation-only descriptions cap at 1 unless a real refactor
    # verb is present (verbose docs shouldn't inflate scope).
    if _is_doc_only(description) and high_hits == 0:
        score = min(score, 1)

    return score


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
