"""Filesystem secret scanner."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from devflow.core.gate_report import CheckResult

if TYPE_CHECKING:
    from devflow.integrations.gate.context import GateContext

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
SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".so", ".whl", ".egg", ".lock", ".png", ".jpg", ".gif",
})
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".devflow", "node_modules", ".ruff_cache",
    "assets",  # Agent/skill .md files contain code examples with fake secrets.
    "tests",  # Test files contain intentional fake secrets for scanner testing.
})


def _should_skip(path: Path, root: Path, ctx: GateContext | None) -> bool:
    """Return True if *path* should be skipped based on extension, dir, or ctx excludes."""
    if path.suffix in SKIP_EXTENSIONS:
        return True
    if any(skip in path.parts for skip in SKIP_DIRS):
        return True
    if ctx is None:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return ctx.is_excluded(rel)


def _scan_file(path: Path, root: Path) -> list[str]:
    """Scan a single file for secrets, return list of findings."""
    try:
        content = path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []

    findings = []
    for secret_name, pattern in SECRET_PATTERNS:
        if pattern.search(content):
            rel = path.relative_to(root)
            findings.append(f"  {rel}: possible {secret_name}")
    return findings


def scan_secrets(base: Path | None = None, ctx: GateContext | None = None) -> CheckResult:
    """Scan project files for potential leaked secrets.

    When *ctx* is a build context with changed_files, only those files are
    scanned. In audit mode (or no context), the entire repo is scanned.
    """
    root = base or Path.cwd()
    findings: list[str] = []

    if ctx and ctx.mode == "build" and ctx.changed_files:
        # Build mode: only scan changed files.
        for rel_path in ctx.scoped_files(root):
            full = root / rel_path
            if not full.is_file():
                continue
            if _should_skip(full, root, ctx):
                continue
            findings.extend(_scan_file(full, root))
    else:
        # Audit mode: scan the entire repo.
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path, root, ctx):
                continue
            findings.extend(_scan_file(path, root))

    if findings:
        return CheckResult(
            name="secrets",
            passed=False,
            message=f"{len(findings)} potential secret(s) found",
            details="\n".join(findings[:20]),
        )
    return CheckResult(name="secrets", passed=True, message="No secrets detected")
