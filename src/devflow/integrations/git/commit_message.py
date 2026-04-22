"""Conventional Commits templating — pure functions, no I/O."""

from __future__ import annotations

from devflow.core.models import Feature

# Max length for PR titles and commit summaries (Conventional Commits best practice).
_MAX_LEN = 70


def _commit_prefix(feature: Feature) -> str:
    """Return the Conventional Commits prefix for a feature.

    Uses ``metadata.commit_type`` when set by the planner (e.g. refactor, docs).
    Falls back to ``fix:`` for quick workflow, ``feat:`` otherwise.
    """
    if feature.metadata.commit_type:
        return feature.metadata.commit_type
    return "fix" if feature.workflow == "quick" else "feat"


def _normalize_description(description: str) -> str:
    """Lowercase the first letter, strip trailing punctuation, and sanitize colons.

    Colons in the description are replaced with em-dashes so they don't look
    like a second Conventional Commits type prefix (e.g. "feat: foo: bar").
    """
    desc = description.strip().rstrip(".!?")
    desc = desc.replace("\n", " ").replace("\r", "")
    desc = desc.replace(":", " —")
    return desc[0].lower() + desc[1:] if desc else desc


def _truncate_at_word(text: str, max_len: int, min_prefix: int = 0) -> str:
    """Truncate text at the last word boundary within max_len."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > min_prefix:
        truncated = truncated[:last_space]
    return truncated


def build_commit_message(feature: Feature, suffix: str | None = None) -> str:
    """Build a standardized Conventional Commits message for a feature.

    Format:
        feat: Add caching layer                 (no suffix — used for PR title)
        feat: Add caching layer — implementing  (with suffix — intermediate commits)

    Args:
        feature: The feature this commit is for.
        suffix: Optional qualifier (e.g. "implementing", "fixing",
                "leftover changes"). Appended after an em-dash.
    """
    type_ = _commit_prefix(feature)
    scope = feature.metadata.scope
    prefix = f"{type_}({scope})" if scope else type_
    raw = feature.metadata.title or feature.description
    desc = _normalize_description(raw)
    base = f"{prefix}: {desc}"

    if suffix:
        base = f"{base} — {suffix}"

    return _truncate_at_word(base, _MAX_LEN, min_prefix=len(prefix) + 2)


def build_pr_title(feature: Feature) -> str:
    """Build a Conventional Commits PR title (no suffix)."""
    return build_commit_message(feature)
