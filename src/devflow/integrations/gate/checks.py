"""Stack-specific check definitions and subprocess execution."""

from __future__ import annotations

import subprocess
from pathlib import Path

from devflow.core.paths import venv_env
from devflow.integrations.gate.report import CheckDef, CheckResult, ParseOutput


def _parse_pytest(returncode: int, stdout: str) -> tuple[str, str]:
    """Extract the pytest summary line from stdout."""
    last_line = stdout.strip().split("\n")[-1] if stdout.strip() else ""
    if returncode == 0:
        return last_line, ""
    return last_line or "Tests failed", stdout[:2000]


STACK_CHECKS: dict[str, tuple[CheckDef, ...]] = {
    "python": (
        CheckDef("ruff", ["ruff", "check", "."]),
        CheckDef(
            "pytest",
            ["python", "-m", "pytest", "-q", "--tb=short"],
            timeout=120,
            parse_output=_parse_pytest,
        ),
    ),
    "typescript": (
        CheckDef("biome", ["npx", "biome", "check", "."]),
        CheckDef("vitest", ["npx", "vitest", "run", "--reporter=verbose"], timeout=120),
    ),
    "php": (
        CheckDef("pint", ["./vendor/bin/pint", "--test"]),
        CheckDef("pest", ["./vendor/bin/pest", "--compact"], timeout=120),
    ),
}


def checks_for_stack(stack: str | None) -> tuple[CheckDef, ...]:
    """Return the check definitions for *stack*, defaulting to python."""
    return STACK_CHECKS.get(stack or "python", STACK_CHECKS["python"])


def _build_command_result(
    name: str,
    returncode: int,
    output: str,
    parse_output: ParseOutput | None,
) -> CheckResult:
    """Interpret a command's exit code and output as a CheckResult."""
    if parse_output is not None:
        message, details = parse_output(returncode, output)
    elif returncode == 0:
        message, details = "No issues", ""
    else:
        issue_count = output.count("\n")
        message = f"{issue_count} issues found"
        details = output[:2000]
    return CheckResult(
        name=name, passed=returncode == 0, message=message, details=details,
    )


def run_command_check(
    name: str,
    cmd: list[str],
    cwd: Path,
    timeout: int = 60,
    parse_output: ParseOutput | None = None,
    env: dict[str, str] | None = None,
) -> CheckResult:
    """Run an external tool and return a CheckResult.

    Args:
        name: Human-readable check name (e.g. "ruff", "pytest").
        cmd: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Maximum seconds before killing the process.
        parse_output: Optional callback ``(returncode, stdout) -> (message, details)``
            for custom summary extraction. When *None*, a generic summary is used.
        env: Pre-computed venv-aware environment (saves ``os.environ.copy()``
            when running many checks in parallel).  Built lazily when *None*.

    Returns:
        CheckResult with *passed=True* when the tool exits 0 **or** is missing.
        Missing tools are reported but never fail the gate.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
            env=env if env is not None else venv_env(cwd),
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            passed=True,
            skipped=True,
            message=f"{name} not found in PATH",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")

    # When a tool writes its error only to stderr (e.g. "No module named pytest"
    # during collection), stdout is empty and details would silently disappear.
    # Fall back to stderr so the caller always sees a useful error message.
    output = result.stdout if result.stdout else result.stderr

    return _build_command_result(name, result.returncode, output, parse_output)
