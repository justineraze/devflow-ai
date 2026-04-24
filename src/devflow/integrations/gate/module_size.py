"""Module size check — detect oversized Python files in the diff."""

from __future__ import annotations

import subprocess
from pathlib import Path

from devflow.integrations.gate.report import CheckResult

DEFAULT_MAX_LINES = 400
_SRC_DIR = "src"


def _modified_py_files(cwd: Path) -> list[str]:
    """Return .py files modified in the current branch diff (vs HEAD~1).

    Falls back to an empty list if git is unavailable or the repo has no
    commits yet.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    return [
        f for f in result.stdout.strip().split("\n")
        if f.endswith(".py") and f.startswith(_SRC_DIR + "/")
    ]


def _count_non_empty_lines(path: Path) -> int:
    """Count non-blank lines in a file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def check_module_size(
    base: Path | None = None,
    max_lines: int = DEFAULT_MAX_LINES,
) -> CheckResult:
    """Check that modified Python modules don't exceed *max_lines* non-empty lines.

    Returns a **warning-style** result: ``passed`` is always ``True`` so the
    gate doesn't block, but violations are surfaced for the fixing agent.

    Args:
        base: Project root (defaults to cwd).
        max_lines: Threshold for non-empty lines (default 400).
    """
    cwd = base or Path.cwd()
    modified = _modified_py_files(cwd)

    if not modified:
        return CheckResult(
            name="module_size", passed=True, message="No modified modules to check",
        )

    violations: list[str] = []
    for rel_path in modified:
        full_path = cwd / rel_path
        if not full_path.is_file():
            continue
        count = _count_non_empty_lines(full_path)
        if count > max_lines:
            violations.append(f"{rel_path}: {count} lines (max {max_lines})")

    if not violations:
        return CheckResult(
            name="module_size", passed=True, message="All modified modules within size limit",
        )

    return CheckResult(
        name="module_size",
        passed=True,
        message=f"{len(violations)} module(s) exceed {max_lines} lines (warning)",
        details="\n".join(violations),
    )
