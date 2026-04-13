"""Quality gate: automated checks for lint, tests, and secrets detection."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

# Patterns that likely indicate leaked secrets.
_API_KEY_RE = r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{20,}['\"]"
_SECRET_RE = r"(?i)(secret|password|passwd|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Key", re.compile(r"(?i)aws_secret_access_key\s*=\s*\S+")),
    ("Generic API Key", re.compile(_API_KEY_RE)),
    ("Generic Secret", re.compile(_SECRET_RE)),
    ("Private Key", re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----")),
]

# Files to skip when scanning for secrets.
SKIP_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".so", ".whl", ".egg", ".lock", ".png", ".jpg", ".gif",
}
SKIP_DIRS: set[str] = {
    ".git", ".venv", "venv", "__pycache__", ".devflow", "node_modules", ".ruff_cache",
    "assets",  # Agent/skill .md files contain code examples with fake secrets.
    "tests",  # Test files contain intentional fake secrets for scanner testing.
}


@dataclass
class CheckResult:
    """Result of a single quality gate check."""

    name: str
    passed: bool
    message: str = ""
    details: str = ""


@dataclass
class GateReport:
    """Aggregated quality gate report."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return True if all checks passed."""
        return all(c.passed for c in self.checks)

    def add(self, check: CheckResult) -> None:
        """Add a check result."""
        self.checks.append(check)


# Type alias for a check definition: (name, cmd, timeout, parse_output).
CheckDef = tuple[str, list[str], int, Callable[[int, str], tuple[str, str]] | None]

STACK_CHECKS: dict[str, list[CheckDef]] = {
    "python": [
        ("ruff", ["ruff", "check", "src/", "tests/"], 60, None),
        ("pytest", ["python", "-m", "pytest", "tests/", "-q", "--tb=short"], 120, None),
    ],
    "typescript": [
        ("biome", ["npx", "biome", "check", "."], 60, None),
        ("vitest", ["npx", "vitest", "run", "--reporter=verbose"], 120, None),
    ],
    "php": [
        ("pint", ["./vendor/bin/pint", "--test"], 60, None),
        ("pest", ["./vendor/bin/pest", "--compact"], 120, None),
    ],
}

# Pytest checks use a custom parser — patch it into the registry.
# Done after _parse_pytest is defined (see below).


def _checks_for_stack(stack: str | None) -> list[CheckDef]:
    """Return the check definitions for *stack*, defaulting to python."""
    return STACK_CHECKS.get(stack or "python", STACK_CHECKS["python"])


def _run_command_check(
    name: str,
    cmd: list[str],
    cwd: Path,
    timeout: int = 60,
    parse_output: Callable[[int, str], tuple[str, str]] | None = None,
) -> CheckResult:
    """Run an external tool and return a CheckResult.

    Args:
        name: Human-readable check name (e.g. "ruff", "pytest").
        cmd: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Maximum seconds before killing the process.
        parse_output: Optional callback ``(returncode, stdout) -> (message, details)``
            for custom summary extraction. When *None*, a generic summary is used.

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
        )
    except FileNotFoundError:
        return CheckResult(name=name, passed=True, message=f"{name} not found — skipped")
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")

    if parse_output is not None:
        message, details = parse_output(result.returncode, result.stdout)
    else:
        if result.returncode == 0:
            message, details = "No issues", ""
        else:
            message = f"{result.stdout.count(chr(10))} issues found"
            details = result.stdout[:2000]

    passed = result.returncode == 0
    return CheckResult(name=name, passed=passed, message=message, details=details)


def _parse_pytest(returncode: int, stdout: str) -> tuple[str, str]:
    """Extract the pytest summary line from stdout."""
    last_line = stdout.strip().split("\n")[-1] if stdout.strip() else ""
    if returncode == 0:
        return last_line, ""
    return last_line or "Tests failed", stdout[:2000]


# Patch pytest's custom parser into the registry now that _parse_pytest is defined.
STACK_CHECKS["python"][1] = (
    "pytest", ["python", "-m", "pytest", "tests/", "-q", "--tb=short"], 120, _parse_pytest,
)


def run_ruff(base: Path | None = None) -> CheckResult:
    """Run ruff linter on the project."""
    return _run_command_check(
        name="ruff",
        cmd=["ruff", "check", "src/", "tests/"],
        cwd=base or Path.cwd(),
    )


def run_pytest(base: Path | None = None) -> CheckResult:
    """Run pytest on the project."""
    return _run_command_check(
        name="pytest",
        cmd=["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
        cwd=base or Path.cwd(),
        timeout=120,
        parse_output=_parse_pytest,
    )


def scan_secrets(base: Path | None = None) -> CheckResult:
    """Scan project files for potential leaked secrets."""
    root = base or Path.cwd()
    findings: list[str] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in SKIP_EXTENSIONS:
            continue
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue

        try:
            content = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        for secret_name, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                rel = path.relative_to(root)
                findings.append(f"  {rel}: possible {secret_name}")

    if findings:
        return CheckResult(
            name="secrets",
            passed=False,
            message=f"{len(findings)} potential secret(s) found",
            details="\n".join(findings[:20]),
        )
    return CheckResult(name="secrets", passed=True, message="No secrets detected")


def run_gate(base: Path | None = None, stack: str | None = None) -> GateReport:
    """Run all quality gate checks and return the report.

    Args:
        base: Project root directory (defaults to cwd).
        stack: Tech stack name (e.g. "python", "typescript", "php").
            Determines which lint/test tools to run. Defaults to "python".
    """
    cwd = base or Path.cwd()
    report = GateReport()
    for name, cmd, timeout, parse_output in _checks_for_stack(stack):
        report.add(_run_command_check(name, cmd, cwd, timeout, parse_output))
    report.add(scan_secrets(base))
    return report


def render_gate_report(report: GateReport) -> None:
    """Display the quality gate report using Rich."""
    lines = Text()
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        style = "green" if check.passed else "red"
        lines.append(f"  {icon} ", style=style)
        lines.append(f"{check.name}: ", style="bold")
        lines.append(f"{check.message}\n", style=style)
        if check.details:
            lines.append(f"    {check.details[:500]}\n", style="dim")

    verdict = "PASSED" if report.passed else "FAILED"
    border = "green" if report.passed else "red"

    console.print(Panel(lines, title=f"Quality Gate — {verdict}", border_style=border))
