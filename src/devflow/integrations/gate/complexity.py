"""Cyclomatic complexity check via ruff C901."""

from __future__ import annotations

import subprocess
from pathlib import Path

from devflow.core.paths import venv_env
from devflow.integrations.gate.report import CheckResult

DEFAULT_MAX_COMPLEXITY = 10
_TIMEOUT = 60


def check_complexity(
    base: Path | None = None,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> CheckResult:
    """Run ``ruff check --select C901`` and report over-complex functions.

    Returns a **warning-style** result: ``passed`` is always ``True`` so the
    gate doesn't block, but *message* and *details* surface the violations
    for the fixing agent to see.

    Args:
        base: Project root (defaults to cwd).
        max_complexity: McCabe threshold (default 10).
    """
    cwd = base or Path.cwd()
    cmd = [
        "ruff", "check",
        "--select", "C901",
        "--output-format", "text",
        "--config", f"lint.mccabe.max-complexity = {max_complexity}",
        ".",
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
            passed=False,
            skipped=True,
            message="ruff not found in PATH",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="complexity", passed=False, message="complexity check timed out",
        )

    output = result.stdout.strip() if result.stdout else ""

    if result.returncode == 0 or not output:
        return CheckResult(
            name="complexity", passed=True, message="No complex functions",
        )

    # Violations found — report as WARNING (passed=True).
    lines = output.split("\n")
    count = len(lines)
    return CheckResult(
        name="complexity",
        passed=True,
        message=f"{count} function(s) exceed complexity {max_complexity} (warning)",
        details=output[:2000],
    )
