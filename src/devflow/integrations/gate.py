"""Quality gate: automated checks for lint, tests, and secrets detection."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from rich.panel import Panel
from rich.text import Text

from devflow.core.paths import venv_env
from devflow.ui.console import console

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
    """Result of a single quality gate check.

    A check that could not run (tool missing, etc.) is reported with
    ``skipped=True`` instead of being silently marked as passed.
    Skipped checks are surfaced in the report but do not fail the gate.
    """

    name: str
    passed: bool
    message: str = ""
    details: str = ""
    skipped: bool = False


@dataclass
class GateReport:
    """Aggregated quality gate report."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return True when every non-skipped check passed."""
        return all(c.passed for c in self.checks if not c.skipped)

    @property
    def has_skipped(self) -> bool:
        """True when at least one check was skipped (e.g. tool missing)."""
        return any(c.skipped for c in self.checks)

    def add(self, check: CheckResult) -> None:
        """Add a check result."""
        self.checks.append(check)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report for persistence and agent consumption."""
        return {
            "passed": self.passed,
            "has_skipped": self.has_skipped,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "skipped": c.skipped,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


# Type alias for an output parser: (returncode, stdout) -> (message, details).
ParseOutput = Callable[[int, str], tuple[str, str]]


class CheckDef(NamedTuple):
    """Definition of a quality gate check (lint, test, etc.)."""

    name: str
    cmd: list[str]
    timeout: int = 60
    parse_output: ParseOutput | None = None


def _parse_pytest(returncode: int, stdout: str) -> tuple[str, str]:
    """Extract the pytest summary line from stdout."""
    last_line = stdout.strip().split("\n")[-1] if stdout.strip() else ""
    if returncode == 0:
        return last_line, ""
    return last_line or "Tests failed", stdout[:2000]


STACK_CHECKS: dict[str, list[CheckDef]] = {
    "python": [
        CheckDef("ruff", ["ruff", "check", "src/", "tests/"]),
        CheckDef(
            "pytest",
            ["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
            timeout=120,
            parse_output=_parse_pytest,
        ),
    ],
    "typescript": [
        CheckDef("biome", ["npx", "biome", "check", "."]),
        CheckDef("vitest", ["npx", "vitest", "run", "--reporter=verbose"], timeout=120),
    ],
    "php": [
        CheckDef("pint", ["./vendor/bin/pint", "--test"]),
        CheckDef("pest", ["./vendor/bin/pest", "--compact"], timeout=120),
    ],
}


def _checks_for_stack(stack: str | None) -> list[CheckDef]:
    """Return the check definitions for *stack*, defaulting to python."""
    return STACK_CHECKS.get(stack or "python", STACK_CHECKS["python"])


def _run_command_check(
    name: str,
    cmd: list[str],
    cwd: Path,
    timeout: int = 60,
    parse_output: ParseOutput | None = None,
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
            env=venv_env(),
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            passed=False,
            skipped=True,
            message=f"{name} not found in PATH",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")

    # When a tool writes its error only to stderr (e.g. "No module named pytest"
    # during collection), stdout is empty and details would silently disappear.
    # Fall back to stderr so the caller always sees a useful error message.
    output = result.stdout if result.stdout else result.stderr

    if parse_output is not None:
        message, details = parse_output(result.returncode, output)
    elif result.returncode == 0:
        message, details = "No issues", ""
    else:
        message = f"{output.count(chr(10))} issues found"
        details = output[:2000]

    passed = result.returncode == 0
    return CheckResult(name=name, passed=passed, message=message, details=details)


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
    """Run all quality gate checks in parallel and return the report.

    All checks (lint, tests, secret scan) are independent subprocess or
    I/O-bound operations — running them concurrently cuts wall-time by
    roughly the slowest-minus-others factor on typical Python repos
    (ruff ~300ms, pytest several seconds).

    Args:
        base: Project root directory (defaults to cwd).
        stack: Tech stack name (e.g. "python", "typescript", "php").
            Determines which lint/test tools to run. Defaults to "python".
    """
    cwd = base or Path.cwd()
    checks = _checks_for_stack(stack)
    report = GateReport()

    with ThreadPoolExecutor(max_workers=len(checks) + 1) as pool:
        command_futures = [
            pool.submit(
                _run_command_check,
                c.name, c.cmd, cwd, c.timeout, c.parse_output,
            )
            for c in checks
        ]
        secrets_future = pool.submit(scan_secrets, base)

        # Preserve declared order for a stable report layout.
        for fut in command_futures:
            report.add(fut.result())
        report.add(secrets_future.result())

    return report


def run_gate_phase(
    base: Path | None = None,
    stack: str | None = None,
    feature_id: str | None = None,
) -> tuple[bool, str, object]:
    """Run the gate phase locally (ruff + pytest + secrets).

    When *feature_id* is provided, the structured report is persisted as
    ``.devflow/<feature_id>/gate.json`` so a follow-up fixing phase can load
    the exact failures instead of parsing free-form text.

    Returns ``(passed, summary_text, metrics)`` — metrics is a blank
    PhaseMetrics since the gate is local and incurs no model cost.
    """
    import json

    from devflow.core.artifacts import write_artifact
    from devflow.core.metrics import PhaseMetrics

    report = run_gate(base, stack=stack)

    if feature_id:
        write_artifact(
            feature_id, "gate.json", json.dumps(report.to_dict(), indent=2), base,
        )

    lines = []
    for check in report.checks:
        if check.skipped:
            icon = "⚠"
        elif check.passed:
            icon = "✓"
        else:
            icon = "✗"
        lines.append(f"{icon} {check.name}: {check.message}")
        if not check.passed and not check.skipped and check.details:
            for detail in check.details.split("\n")[:10]:
                lines.append(f"    {detail}")

    return report.passed, "\n".join(lines), PhaseMetrics()


def render_gate_report(report: GateReport) -> None:
    """Render the quality gate as a Rich panel with per-check details.

    Three states per check:
    - passed → green ✓
    - skipped (tool missing, etc.) → yellow ⚠ (does not fail the gate)
    - failed → red ✗
    """
    body = Text()
    for idx, check in enumerate(report.checks):
        if check.skipped:
            icon, icon_style, name_style, msg_style = (
                "⚠", "yellow bold", "yellow", "yellow",
            )
        elif check.passed:
            icon, icon_style, name_style, msg_style = (
                "✓", "green bold", "white", "dim",
            )
        else:
            icon, icon_style, name_style, msg_style = (
                "✗", "red bold", "red", "red",
            )

        if idx:
            body.append("\n")
        body.append(f"  {icon}  ", style=icon_style)
        body.append(check.name.ljust(10), style=f"bold {name_style}")
        body.append(check.message, style=msg_style)

        if not check.passed and not check.skipped and check.details:
            for detail in check.details.split("\n")[:8]:
                if detail.strip():
                    body.append(f"\n       {detail[:200]}", style="dim red")

    if not report.passed:
        verdict, verdict_style, border = "FAILED", "reverse red bold", "red"
    elif report.has_skipped:
        verdict, verdict_style, border = (
            "PASSED (with skipped)", "reverse yellow bold", "yellow",
        )
    else:
        verdict, verdict_style, border = "PASSED", "reverse green bold", "green"

    console.print(Panel(
        body,
        title=Text(f" Gate — {verdict} ", style=verdict_style),
        border_style=border,
        padding=(1, 2),
    ))
