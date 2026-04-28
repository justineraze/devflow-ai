"""Module size check — detect oversized Python files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from devflow.integrations.gate.report import CheckResult

if TYPE_CHECKING:
    from devflow.integrations.gate.context import GateContext

DEFAULT_MAX_LINES = 400
_SRC_DIR = "src"


def _count_non_empty_lines(path: Path) -> int:
    """Count non-blank lines in a file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def _collect_py_files(cwd: Path, ctx: GateContext | None) -> list[str]:
    """Return the list of .py file paths to check.

    Build mode with context → changed .py files under src/.
    Audit mode or no context → all .py files under src/ (rglob).
    """
    if ctx and ctx.mode == "build" and ctx.changed_files:
        return [
            str(f) for f in ctx.scoped_files(cwd)
            if str(f).endswith(".py") and str(f).startswith(_SRC_DIR + "/")
        ]

    # Audit mode: scan all .py under src/.
    src = cwd / _SRC_DIR
    if not src.is_dir():
        return []
    return [
        str(p.relative_to(cwd))
        for p in src.rglob("*.py")
        if p.is_file() and not (ctx and ctx.is_excluded(p.relative_to(cwd)))
    ]


def check_module_size(
    base: Path | None = None,
    max_lines: int = DEFAULT_MAX_LINES,
    ctx: GateContext | None = None,
) -> CheckResult:
    """Check that Python modules don't exceed *max_lines* non-empty lines.

    In build mode, only changed files are checked.
    In audit mode, all files under ``src/`` are checked.

    Returns a **warning-style** result: ``passed`` is always ``True`` so the
    gate doesn't block, but violations are surfaced for the fixing agent.

    Args:
        base: Project root (defaults to cwd).
        max_lines: Threshold for non-empty lines (default 400).
        ctx: Gate context (build vs audit scoping).
    """
    cwd = base or Path.cwd()
    py_files = _collect_py_files(cwd, ctx)

    if not py_files:
        label = "No files to check" if ctx and ctx.mode == "build" else "No modules to check"
        return CheckResult(
            name="module_size", passed=True, message=label,
        )

    violations: list[str] = []
    for rel_path in py_files:
        full_path = cwd / rel_path
        if not full_path.is_file():
            continue
        count = _count_non_empty_lines(full_path)
        if count > max_lines:
            violations.append(f"{rel_path}: {count} lines (max {max_lines})")

    if not violations:
        return CheckResult(
            name="module_size", passed=True, message="All modules within size limit",
        )

    return CheckResult(
        name="module_size",
        passed=True,
        message=f"{len(violations)} module(s) exceed {max_lines} lines (warning)",
        details="\n".join(violations),
    )
