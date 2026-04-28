"""PR body building, plan parsing, and push/gh orchestration."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import structlog

from devflow.core.artifacts import load_phase_output
from devflow.core.models import Feature

from .repo import (
    commit_changes,
    get_branch_diff_summary,
    has_commits_ahead,
    push_branch,
)

_log = structlog.get_logger(__name__)


def parse_plan_summary(plan_output: str) -> str:
    """Extract the one-line summary from the plan header.

    Looks for: ``## Plan: <id> — <summary>``
    Supports em-dash (—), en-dash (–), and regular hyphen (-).
    Returns the summary text, or "" if the header is absent.
    """
    match = re.search(r"^##\s+Plan:[^\n]*?(?:—|–| - )\s*(.+)$", plan_output, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def parse_plan_changes(plan_output: str, max_items: int = 5) -> str:
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


def build_pr_body(feature: Feature) -> str:
    """Build the PR description from planning and gate phase artifacts.

    Summary and Changes are extracted from the planner's structured output.
    Falls back to ``feature.description`` when the planning phase is absent
    (quick/fix workflows) or produced no parseable header.
    """
    plan_output = load_phase_output(feature.id, "planning") or ""

    summary = parse_plan_summary(plan_output) if plan_output else ""
    changes = parse_plan_changes(plan_output) if plan_output else ""

    parts = ["## Summary", "", summary or feature.description, ""]

    if changes:
        parts.extend(["## Changes", "", changes, ""])

    gate_output = load_phase_output(feature.id, "gate") or ""
    if gate_output:
        parts.extend(["## Quality gate", "", gate_output, ""])

    parts.append("---")
    parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")
    return "\n".join(parts)


def _format_diff_stat(base_branch: str) -> str:
    """Format the diff stat block injected into the PR body."""
    summary = get_branch_diff_summary(base_branch)
    lines = [
        f"+{summary['lines_added']} -{summary['lines_removed']} "
        f"in {summary['files_changed']} files",
    ]
    for path in summary.get("paths", [])[:15]:
        lines.append(f"  {path}")
    return "\n".join(lines)


def _create_gh_pr(
    title: str, body: str, base_branch: str, cwd: Path,
) -> str | None:
    """Invoke ``gh pr create`` and return the PR URL or None on failure."""
    try:
        result = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body,
             "--base", base_branch],
            capture_output=True, text=True, cwd=str(cwd), timeout=120,
        )
    except subprocess.TimeoutExpired:
        _log.warning("gh pr create timed out")
        return None
    if result.returncode == 0:
        return result.stdout.strip()
    _log.warning("PR creation failed: %s", result.stderr.strip())
    return None


def _branch_diff_against(base_branch: str) -> str:
    """Return the full ``git diff <base>..HEAD`` output."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base_branch}..HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def push_and_create_pr(
    feature: Feature,
    branch: str,
    exclude: list[str] | None = None,
    base_branch: str = "main",
) -> str | None:
    """Push branch and create a GitHub PR.

    Commits any uncommitted changes first as a safety net. *exclude* is
    forwarded to ``commit_changes`` so user scratch files captured before
    the build started stay out of the final PR.
    Returns the PR URL, or None if creation failed.
    """
    from .smart_messages import (
        generate_commit_message,
        generate_pr_body,
        generate_pr_title,
    )

    # Safety net: commit anything left uncommitted.
    commit_changes(
        generate_commit_message(feature, phase="leftover changes"),
        exclude=exclude,
    )

    if not has_commits_ahead(base_branch):
        _log.info("No changes to push — branch is identical to %s", base_branch)
        return None

    pushed, stderr = push_branch(branch)
    if not pushed:
        _log.warning("Push failed: %s", stderr)
        return None

    plan = load_phase_output(feature.id, "planning") or ""
    body = generate_pr_body(feature, plan=plan, diff_stat=_format_diff_stat(base_branch))
    # PR title: build it from the actual diff so the Conventional Commits
    # type reflects what changed (feat / fix / refactor / docs / …) rather
    # than echoing the user's prompt verbatim.
    diff = _branch_diff_against(base_branch)
    title = generate_pr_title(feature, diff=diff)
    return _create_gh_pr(title, body, base_branch, Path.cwd())
