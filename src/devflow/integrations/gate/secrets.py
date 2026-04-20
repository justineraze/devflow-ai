"""Filesystem secret scanner."""

from __future__ import annotations

import re
from pathlib import Path

from devflow.integrations.gate.report import CheckResult

# Patterns that likely indicate leaked secrets.
_API_KEY_RE = r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{20,}['\"]"
_SECRET_RE = r"(?i)(secret|password|passwd|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Key", re.compile(r"(?i)aws_secret_access_key\s*=\s*\S+")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    ("GitHub PAT", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("Anthropic API Key", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    ("Slack Token", re.compile(r"xox[bprs]-[A-Za-z0-9\-]{10,}")),
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
