"""Pure data types for the quality gate report.

These types live in ``core/`` because they are consumed by multiple
layers (integrations, ui, setup) and must not create cross-layer
import dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

# Maximum byte length kept in CheckResult.details. Captures enough of a
# tool's stdout/stderr to be actionable in the gate panel without bloating
# the persisted gate.json artifact (and the prompts that read it).
MAX_CHECK_DETAILS_LEN = 2000


@dataclass
class CheckResult:
    """Result of a single quality gate check.

    A check that could not run (tool missing, etc.) is reported with
    ``skipped=True`` instead of being silently marked as passed.
    Skipped checks are surfaced in the report but do not fail the gate.
    ``duration_s`` records wall-clock seconds spent running the check.
    """

    name: str
    passed: bool
    message: str = ""
    details: str = ""
    skipped: bool = False
    duration_s: float = 0.0


@dataclass
class GateReport:
    """Aggregated quality gate report."""

    checks: list[CheckResult] = field(default_factory=list)
    custom: bool = False

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
            "custom": self.custom,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "skipped": c.skipped,
                    "message": c.message,
                    "details": c.details,
                    "duration_s": round(c.duration_s, 3),
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
