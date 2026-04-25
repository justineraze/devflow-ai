"""Gate execution context — what the gate should check.

Two modes:
- **audit** (``devflow check``): full repo scan, informational report.
- **build** (during a build): scoped to the diff, blocking.

The context is computed once and passed to every check.
"""

from __future__ import annotations

import fnmatch
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from devflow.core.config import load_config

_log = logging.getLogger(__name__)


@dataclass
class GateContext:
    """What the gate should check."""

    mode: Literal["audit", "build"]
    changed_files: list[Path] = field(default_factory=list)
    base_sha: str = ""
    exclude_patterns: list[str] = field(default_factory=list)

    # ── helpers ────────────────────────────────────────────────────

    def is_excluded(self, path: Path | str) -> bool:
        """Return True if *path* matches any exclude pattern (fnmatch)."""
        s = str(path)
        return any(fnmatch.fnmatch(s, pat) for pat in self.exclude_patterns)

    def scoped_files(self, root: Path) -> list[Path]:
        """Return the files this context wants checked.

        Build mode → ``changed_files`` (filtered by excludes).
        Audit mode → empty list (caller should fall back to scanning).
        """
        if self.mode == "audit":
            return []
        return [f for f in self.changed_files if not self.is_excluded(f)]


_GIT_DIFF_TIMEOUT = 30


def _git_diff_files(base_sha: str, cwd: Path) -> list[Path]:
    """Return files changed between *base_sha* and HEAD.

    Returns an empty list when git is unavailable, the diff times out, or
    the command exits non-zero. The failure is logged at warning level so
    a misconfigured base SHA surfaces during a build instead of silently
    falling back to an empty diff.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=_GIT_DIFF_TIMEOUT,
        )
    except FileNotFoundError:
        _log.warning("git not found in PATH — gate scoping falls back to empty diff")
        return []
    except subprocess.TimeoutExpired:
        _log.warning(
            "git diff timed out after %ds against %s — empty diff used",
            _GIT_DIFF_TIMEOUT, base_sha,
        )
        return []

    if result.returncode != 0:
        _log.warning(
            "git diff %s..HEAD failed (exit %d): %s",
            base_sha, result.returncode, result.stderr.strip()[:200],
        )
        return []

    return [Path(f) for f in result.stdout.strip().split("\n") if f.strip()]


def build_context(
    *,
    mode: Literal["audit", "build"] = "audit",
    base_sha: str = "",
    base: Path | None = None,
) -> GateContext:
    """Construct the right GateContext for the current execution.

    Args:
        mode: ``"audit"`` for ``devflow check``, ``"build"`` during a build.
        base_sha: SHA to diff against (build mode only).
        base: Project root directory (defaults to cwd).
    """
    cwd = base or Path.cwd()
    config = load_config(base)
    exclude = config.gate.exclude or []

    changed: list[Path] = []
    if mode == "build" and base_sha:
        changed = _git_diff_files(base_sha, cwd)

    return GateContext(
        mode=mode,
        changed_files=changed,
        base_sha=base_sha,
        exclude_patterns=exclude,
    )
