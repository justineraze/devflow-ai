"""Plan output parsing — extract metadata from the planning phase output.

Pure functions with zero dependencies on orchestration or state.
"""

from __future__ import annotations

import re

# Map plan Type: values → Conventional Commits prefixes.
_PLAN_TYPE_TO_COMMIT: dict[str, str] = {
    "new-feature": "feat",
    "extension": "feat",
    "bugfix": "fix",
    "refactor": "refactor",
    "docs": "docs",
    "ci": "ci",
    "test": "test",
    "chore": "chore",
    "perf": "perf",
}


def parse_plan_module(plan_output: str) -> str | None:
    """Extract the module name from the plan's ### Scope section.

    Looks for: ``- Module: <module>``
    Returns the first word of the value, or None if the line is absent.
    """
    match = re.search(r"^\s*-\s+Module:\s+(\S+)", plan_output, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def parse_plan_title(plan_output: str) -> str | None:
    """Extract the concise title from the plan header.

    Looks for: ``## Plan: <feature-id> — <title>``
    Returns the title part after the em-dash, or None if absent.
    """
    match = re.search(r"^##\s+Plan:\s+\S+\s+[—–-]\s+(.+)$", plan_output, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def parse_plan_type(plan_output: str) -> str | None:
    """Extract the Conventional Commits type from the plan's Type: line.

    Looks for: ``- Type: <value>``
    Maps plan-specific values (new-feature, bugfix…) to commit types (feat, fix…).
    Returns None if the line is absent or the value is unknown.
    """
    match = re.search(r"^\s*-\s+Type:\s+(\S+)", plan_output, re.MULTILINE)
    if not match:
        return None
    return _PLAN_TYPE_TO_COMMIT.get(match.group(1).strip().lower())
