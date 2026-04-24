"""Cyclomatic complexity check via ruff C901."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from devflow.core.paths import venv_env
from devflow.integrations.gate.report import CheckResult

if TYPE_CHECKING:
    from devflow.integrations.gate.context import GateContext

DEFAULT_MAX_COMPLEXITY = 10
_TIMEOUT = 60

_log = logging.getLogger(__name__)


def _resolve_complexity_targets(
    cwd: Path, ctx: GateContext | None,
) -> list[str] | None:
    """Return the list of paths to scan, or ``None`` if no Python files apply.

    In build mode with a non-empty diff, return only the changed ``.py`` files.
    Otherwise (audit mode or no context), scan the entire project.
    """
    if ctx and ctx.mode == "build" and ctx.changed_files:
        py_files = [
            str(f) for f in ctx.scoped_files(cwd)
            if str(f).endswith(".py")
        ]
        if not py_files:
            return None
        return py_files
    return ["."]


def _build_complexity_result(
    returncode: int, output: str, max_complexity: int,
) -> CheckResult:
    """Interpret ruff's exit code/output as a warning-style CheckResult."""
    if returncode == 0 or not output:
        if returncode != 0 and not output:
            _log.warning(
                "ruff complexity check returned %d with empty stdout", returncode,
            )
        return CheckResult(
            name="complexity", passed=True, message="No complex functions",
        )

    lines = output.split("\n")
    count = len(lines)
    return CheckResult(
        name="complexity",
        passed=True,
        message=f"{count} function(s) exceed complexity {max_complexity} (warning)",
        details=output[:2000],
    )


def check_complexity(
    base: Path | None = None,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
    ctx: GateContext | None = None,
) -> CheckResult:
    """Run ``ruff check --select C901`` and report over-complex functions.

    In build mode, only the changed ``.py`` files are checked.
    In audit mode (or no context), the entire project is checked.

    Returns a **warning-style** result: ``passed`` is always ``True`` so the
    gate doesn't block, but *message* and *details* surface the violations
    for the fixing agent to see.

    Args:
        base: Project root (defaults to cwd).
        max_complexity: McCabe threshold (default 10).
        ctx: Gate context (build vs audit scoping).
    """
    cwd = base or Path.cwd()

    targets = _resolve_complexity_targets(cwd, ctx)
    if targets is None:
        return CheckResult(
            name="complexity", passed=True,
            message="No Python files in diff",
        )

    cmd = [
        "ruff", "check",
        "--select", "C901",
        "--output-format", "text",
        "--config", f"lint.mccabe.max-complexity = {max_complexity}",
        *targets,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=_TIMEOUT,
            env=venv_env(cwd),
        )
    except FileNotFoundError:
        return CheckResult(
            name="complexity",
            passed=True,
            skipped=True,
            message="ruff not found in PATH",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="complexity", passed=False, message="complexity check timed out",
        )

    output = result.stdout.strip() if result.stdout else ""
    return _build_complexity_result(result.returncode, output, max_complexity)
