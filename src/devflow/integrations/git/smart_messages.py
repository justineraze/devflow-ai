"""AI-generated git messages via backend one-shot calls.

Every public function has a deterministic fallback so the build never
crashes because of a message-generation failure.

Messages are generated through the Backend Protocol's ``one_shot()``
method — the concrete backend (Claude, Gemini, OpenAI…) handles the
actual API/CLI call.
"""

from __future__ import annotations

import re
import subprocess

import structlog

from devflow.core.backend import ModelTier, get_backend
from devflow.core.models import Feature

from .commit_message import MAX_COMMIT_SUBJECT_LEN
from .commit_message import build_commit_message as _template_commit_message

_log = structlog.get_logger(__name__)

# Ceiling for diff content sent to the model (roughly 500 lines × ~80 chars).
_MAX_DIFF_LINES = 500

# Timeout for one-shot calls (seconds).
_ONE_SHOT_TIMEOUT = 30


def _call_one_shot(system: str, user: str) -> str | None:
    """Run a one-shot prompt via the active backend and return trimmed output.

    Returns ``None`` on any failure — the caller is responsible for
    falling back to a deterministic template. The failure is logged at
    warning level so prompt-generation regressions don't disappear into
    silent fallbacks.
    """
    backend = get_backend()
    model = backend.model_name(ModelTier.FAST)
    try:
        return backend.one_shot(
            system=system,
            user=user,
            model=model,
            timeout=_ONE_SHOT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — open fallback for any backend error
        _log.warning("one_shot failed (%s); falling back to template", exc)
        return None


def _truncate_diff(diff: str, max_lines: int = _MAX_DIFF_LINES) -> str:
    """Truncate a diff to *max_lines*, appending a notice if trimmed."""
    lines = diff.splitlines()
    if len(lines) <= max_lines:
        return diff
    return "\n".join(lines[:max_lines]) + "\n\n… (truncated)"


# ── Feature title ──────────────────────────────────────────────────


_TITLE_SYSTEM = (
    "Summarize this development request as a single git-commit subject.\n\n"
    "Rules:\n"
    "- ONE line, max 50 characters, English, lowercase\n"
    "- No period, no surrounding quotes, no markdown\n"
    "- Imperative mood, present tense (\"add\", not \"added\" or \"adding\")\n"
    "- Describe the *intent*, do NOT echo the user's wording verbatim\n"
    "- Skip filler words (\"please\", \"can you\", \"the codebase\", etc.)\n"
    "- Do NOT include a Conventional Commits prefix (no `feat:` / `fix:`),\n"
    "  the build pipeline adds the type later from the diff\n\n"
    "Examples:\n"
    "- add epic support to state machine\n"
    "- extract planning loop into helper\n"
    "- prevent null state_id in linear sync\n"
    "- consolidate console layering violations"
)


def generate_feature_title(prompt: str) -> str:
    """Generate a concise feature title from a long user prompt.

    The result is a *plain* commit-style description (no
    ``feat:``/``fix:`` prefix — the prefix is added downstream by
    :func:`build_commit_message`).  Falls back to the first 80
    characters of the prompt on backend failure.
    """
    result = _call_one_shot(_TITLE_SYSTEM, prompt)
    if result:
        # Strip quotes/period the model might add.
        result = result.strip('"\'').rstrip(".")
        # Drop accidental Conventional Commits prefix the model still
        # emitted despite the instruction not to ("feat: ", "fix: " …).
        result = re.sub(
            r"^(feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert)"
            r"(\([^)]+\))?:\s+",
            "",
            result,
            flags=re.IGNORECASE,
        )
        if result and len(result) <= 80:
            return result
    # Fallback: first line, truncated.
    first_line = prompt.split("\n", 1)[0].strip()
    return first_line[:80]


# ── PR title ───────────────────────────────────────────────────────


_PR_TITLE_SYSTEM = (
    "Generate a Conventional Commits PR title from this diff.\n"
    "Format: <type>(<scope>): <description>\n\n"
    "Rules:\n"
    "- type: feat | fix | refactor | docs | test | chore | perf\n"
    "- scope: the main module touched, optional, omit when >3 modules\n"
    "- description: max 60 chars, lowercase, imperative, no period\n"
    "- Pick the type that matches the *actual diff*, not the user's prompt\n"
    "- ONE line only, no trailing comment, no quotes, no markdown\n\n"
    "Examples:\n"
    "- feat(gate): add custom gate config via yaml\n"
    "- fix(linear): prevent null state_id in sync\n"
    "- refactor(build): extract planning loop into helper\n"
    "- docs: clarify smoke test cadence in CLAUDE.md"
)

# Maximum length for a PR title we'll trust from the model.
# Longer values fall back to the deterministic template.
MAX_PR_TITLE_LEN = 72

# Conventional Commits prefix anchor — used to validate generated titles.
_CC_PREFIX_RE = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert)"
    r"(\([^)]+\))?: \S",
)


def generate_pr_title(feature: Feature, diff: str = "") -> str:
    """Generate a Conventional Commits PR title from the actual diff.

    The model is given the diff so the type prefix reflects what
    *changed*, not what the user *asked for*.  Falls back to the
    deterministic :func:`build_pr_title` template on any failure or when
    the model output does not match the Conventional Commits prefix.
    """
    from .commit_message import build_pr_title as _template_pr_title

    if diff:
        user_parts: list[str] = []
        if feature.description:
            user_parts.append(f"Feature context: {feature.description}")
        user_parts.append(f"Diff:\n```\n{_truncate_diff(diff)}\n```")
        result = _call_one_shot(_PR_TITLE_SYSTEM, "\n\n".join(user_parts))
        if result:
            first_line = result.split("\n", 1)[0].strip().strip('"\'').rstrip(".")
            if (
                first_line
                and len(first_line) <= MAX_PR_TITLE_LEN
                and _CC_PREFIX_RE.match(first_line)
            ):
                return first_line

    return _template_pr_title(feature)


# ── Commit messages ────────────────────────────────────────────────


_COMMIT_SYSTEM = (
    "Generate a Conventional Commits message for this diff.\n"
    "Format: <type>(<scope>): <description>\n\n"
    "Rules:\n"
    "- type: feat | fix | refactor | docs | test | chore | perf\n"
    "- Pick the type that matches the *diff*, not the user prompt.\n"
    "  Renames/extracts → refactor, new behavior → feat, bug repair → fix.\n"
    "- scope: the main module touched (optional, omit if >3 modules)\n"
    "- description: max 50 chars, lowercase, imperative, no period\n"
    "- If the diff is large, focus on the INTENT not the details\n"
    "- ONE line only, no body, no markdown, no quotes\n\n"
    "Examples:\n"
    "- feat(gate): add custom gate config via yaml\n"
    "- fix(linear): prevent null state_id in sync\n"
    "- refactor(build): extract planning loop into helper\n"
    "- test(orchestration): cover gate retry escalation"
)


def _get_staged_diff() -> str:
    """Return the staged diff (git diff --cached), or empty string."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def generate_commit_message(feature: Feature, phase: str = "") -> str:
    """Generate an AI-powered commit message from the staged diff.

    Falls back to the deterministic template on any failure.

    Args:
        feature: The feature being committed.
        phase: Phase name used as suffix in the fallback template
               (e.g. "implementing", "fixing").
    """
    diff = _get_staged_diff()
    if diff:
        user_parts = []
        if feature.description:
            user_parts.append(f"Feature context: {feature.description}")
        user_parts.append(f"Diff:\n```\n{_truncate_diff(diff)}\n```")
        user_prompt = "\n\n".join(user_parts)

        result = _call_one_shot(_COMMIT_SYSTEM, user_prompt)
        if result:
            # Take only the first line, strip quotes.
            first_line = result.split("\n", 1)[0].strip().strip('"\'')
            if first_line and len(first_line) <= MAX_COMMIT_SUBJECT_LEN:
                return first_line

    # Fallback to deterministic template.
    return _template_commit_message(feature, suffix=phase or None)


# ── PR body ────────────────────────────────────────────────────────


_PR_BODY_SYSTEM = (
    "Generate a GitHub PR description in markdown. Structure:\n\n"
    "## Summary\n"
    "2-3 bullet points explaining WHAT changed and WHY.\n\n"
    "## Changes\n"
    "Bullet list of concrete changes (files/modules affected).\n\n"
    "## Testing\n"
    "How this was tested (mention gate checks that passed).\n\n"
    "Rules:\n"
    "- Be concise, no fluff\n"
    "- Focus on the WHY not the WHAT (the diff shows the what)\n"
    "- Max 300 words\n"
    "- No emojis"
)


def generate_pr_body(feature: Feature, plan: str = "", diff_stat: str = "") -> str:
    """Generate an AI-powered PR body from plan + diff stat.

    Falls back to the deterministic template on failure.
    """
    # Lazy: avoid circular import (pr_body imports from smart_messages)
    from .pr_body import build_pr_body as _template_pr_body

    user_parts = []
    if feature.description:
        user_parts.append(f"Feature: {feature.description}")
    if plan:
        user_parts.append(f"Plan:\n{plan}")
    if diff_stat:
        user_parts.append(f"Diff stat:\n```\n{diff_stat}\n```")

    if user_parts:
        result = _call_one_shot(_PR_BODY_SYSTEM, "\n\n".join(user_parts))
        if result:
            # Append the devflow footer.
            footer = (
                "\n\n---\n"
                "Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)"
            )
            return result + footer

    # Fallback to deterministic template.
    return _template_pr_body(feature)
