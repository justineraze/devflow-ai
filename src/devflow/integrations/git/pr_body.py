"""PR body building, plan parsing, and push/gh orchestration."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from devflow.core.artifacts import load_phase_output
from devflow.core.models import Feature
from devflow.ui.console import console

from .commit_message import build_commit_message, build_pr_title
from .repo import _git, commit_changes, has_commits_ahead


def _parse_plan_summary(plan_output: str) -> str:
    """Extract the one-line summary from the plan header.

    Looks for: ``## Plan: <id> — <summary>``
    Supports em-dash (—), en-dash (–), and regular hyphen (-).
    Returns the summary text, or "" if the header is absent.
    """
    match = re.search(r"^##\s+Plan:[^\n]*?(?:—|–| - )\s*(.+)$", plan_output, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def _parse_plan_changes(plan_output: str, max_items: int = 5) -> str:
    """Extract implementation steps as markdown bullets.

    Finds ``### Implementation steps`` and reformats numbered items as
    ``- `` bullets, stripping ``Test: …`` tails (implementation detail,
    not relevant in a PR body).  Returns "" if the section is absent.
    """
    section_match = re.search(
        r"###\s+Implementation steps\s*\n(.*?)(?=\n###|\Z)",
        plan_output,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return ""

    bullets: list[str] = []
    for line in section_match.group(1).splitlines():
        item_match = re.match(r"^\s*\d+\.\s+(.+)", line)
        if not item_match:
            continue
        text = item_match.group(1).strip()
        # Drop "Test: ..." tail — it clutters the PR body.
        text = re.sub(r"\.\s+Test:.*$", "", text, flags=re.IGNORECASE).rstrip(".")
        bullets.append(f"- {text}")
        if len(bullets) >= max_items:
            break

    return "\n".join(bullets)


def _build_pr_body(feature: Feature) -> str:
    """Build the PR description from planning and gate phase artifacts.

    Summary and Changes are extracted from the planner's structured output.
    Falls back to ``feature.description`` when the planning phase is absent
    (quick/fix workflows) or produced no parseable header.
    """
    plan_output = load_phase_output(feature.id, "planning") or ""

    summary = _parse_plan_summary(plan_output) if plan_output else ""
    changes = _parse_plan_changes(plan_output) if plan_output else ""

    parts = ["## Summary", ""]
    parts.append(summary or feature.description)
    parts.append("")

    if changes:
        parts.extend(["## Changes", "", changes, ""])

    gate_output = load_phase_output(feature.id, "gate") or ""
    if gate_output:
        parts.extend(["## Quality gate", "", gate_output, ""])

    parts.append("---")
    parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")
    return "\n".join(parts)


def push_and_create_pr(
    feature: Feature,
    branch: str,
    exclude: list[str] | None = None,
) -> str | None:
    """Push branch and create a GitHub PR.

    Commits any uncommitted changes first as a safety net. *exclude* is
    forwarded to ``commit_changes`` so user scratch files captured before the
    build started stay out of the final PR.
    Returns the PR URL, or None if creation failed.
    """
    cwd = str(Path.cwd())

    # Safety net: commit anything left uncommitted.
    commit_changes(build_commit_message(feature, suffix="leftover changes"), exclude=exclude)

    if not has_commits_ahead():
        console.print("[yellow]No changes to push — branch is identical to main.[/yellow]")
        return None

    # Push.
    push = _git("push", "-u", "origin", branch, timeout=120)
    if push.returncode != 0:
        console.print(f"[red]Push failed: {push.stderr.strip()}[/red]")
        return None

    # Build PR body and title using Conventional Commits format.
    body = _build_pr_body(feature)
    title = build_pr_title(feature)

    pr = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body],
        capture_output=True, text=True, cwd=cwd,
    )
    if pr.returncode == 0:
        return pr.stdout.strip()

    console.print(f"[red]PR creation failed: {pr.stderr.strip()}[/red]")
    return None
