"""Quality gate: automated checks for lint, tests, and secrets detection."""

from __future__ import annotations

import re
import subprocess
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


def run_ruff(base: Path | None = None) -> CheckResult:
    """Run ruff linter on the project."""
    cwd = str(base or Path.cwd())
    try:
        result = subprocess.run(
            ["ruff", "check", "src/", "tests/"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=60,
        )
        if result.returncode == 0:
            return CheckResult(name="ruff", passed=True, message="No lint issues")
        return CheckResult(
            name="ruff",
            passed=False,
            message=f"{result.stdout.count(chr(10))} lint issues found",
            details=result.stdout[:2000],
        )
    except FileNotFoundError:
        return CheckResult(name="ruff", passed=False, message="ruff not installed")
    except subprocess.TimeoutExpired:
        return CheckResult(name="ruff", passed=False, message="ruff timed out")


def run_pytest(base: Path | None = None) -> CheckResult:
    """Run pytest on the project."""
    cwd = str(base or Path.cwd())
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        # Extract summary line (e.g., "33 passed in 0.09s").
        last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
        if result.returncode == 0:
            return CheckResult(name="pytest", passed=True, message=last_line)
        return CheckResult(
            name="pytest",
            passed=False,
            message=last_line or "Tests failed",
            details=result.stdout[:2000],
        )
    except FileNotFoundError:
        return CheckResult(name="pytest", passed=False, message="pytest not installed")
    except subprocess.TimeoutExpired:
        return CheckResult(name="pytest", passed=False, message="Tests timed out")


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


def run_gate(base: Path | None = None) -> GateReport:
    """Run all quality gate checks and return the report."""
    report = GateReport()
    report.add(run_ruff(base))
    report.add(run_pytest(base))
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
