"""Security-sensitive path patterns shared across complexity scoring and gate."""

from __future__ import annotations

CRITICAL_PATH_PATTERNS: tuple[str, ...] = (
    "auth", "secret", "token", "crypto", "payment", "billing", "password",
)
"""Paths whose names match these substrings are treated as critical.

Used by:
- :mod:`devflow.integrations.complexity` to bump the security dimension.
- :mod:`devflow.orchestration.phase_artifacts` to mark critical paths in
  ``files.json`` so the model router never downgrades reviews on them.
"""

__all__ = ["CRITICAL_PATH_PATTERNS"]
