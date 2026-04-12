"""Git operations — branch management, commits, and PR creation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from devflow.models import Feature

console = Console()


def create_branch(feature_id: str) -> str:
    """Create and checkout a git branch for the feature.

    If the branch already exists, switches to it instead.
    Returns the branch name.
    """
    branch = f"feat/{feature_id}"
    cwd = str(Path.cwd())

    result = subprocess.run(
        ["git", "checkout", "-b", branch],
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0:
        subprocess.run(
            ["git", "checkout", branch],
            capture_output=True, text=True, cwd=cwd,
        )
    return branch


def switch_branch(branch: str) -> None:
    """Switch to an existing branch."""
    subprocess.run(
        ["git", "checkout", branch],
        capture_output=True, text=True, cwd=str(Path.cwd()),
    )


def commit_changes(message: str) -> bool:
    """Stage all files and commit if there are changes.

    Returns True if a commit was created, False if nothing to commit.
    """
    cwd = str(Path.cwd())

    subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cwd, capture_output=True,
    )
    if diff.returncode == 0:
        return False

    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd, capture_output=True,
    )
    return True


def has_commits_ahead(base_branch: str = "main") -> bool:
    """Check if current branch has commits ahead of base_branch."""
    result = subprocess.run(
        ["git", "rev-list", "--count", f"{base_branch}..HEAD"],
        capture_output=True, text=True, cwd=str(Path.cwd()),
    )
    return result.stdout.strip() != "0"


def get_diff_stat() -> str:
    """Return git diff --stat of the latest commit."""
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1"],
        capture_output=True, text=True, cwd=str(Path.cwd()),
    )
    return result.stdout.strip()


def push_and_create_pr(feature: Feature, branch: str) -> str | None:
    """Push branch and create a GitHub PR.

    Commits any uncommitted changes first as a safety net.
    Returns the PR URL, or None if creation failed.
    """
    cwd = str(Path.cwd())

    # Safety net: commit anything left uncommitted.
    commit_changes(f"chore({feature.id}): uncommitted changes")

    if not has_commits_ahead():
        console.print("[yellow]No changes to push — branch is identical to main.[/yellow]")
        return None

    # Push.
    push = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True, text=True, cwd=cwd,
    )
    if push.returncode != 0:
        console.print(f"[red]Push failed: {push.stderr.strip()}[/red]")
        return None

    # Build PR body from phase outputs.
    body = _build_pr_body(feature)
    title = feature.description[:70]

    pr = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body],
        capture_output=True, text=True, cwd=cwd,
    )
    if pr.returncode == 0:
        return pr.stdout.strip()

    console.print(f"[red]PR creation failed: {pr.stderr.strip()}[/red]")
    return None


def _build_pr_body(feature: Feature) -> str:
    """Build the PR description from phase outputs."""
    parts = ["## Summary", "", feature.description, ""]

    for phase in feature.phases:
        if phase.status.value != "done" or not phase.output:
            continue
        if phase.name == "planning":
            parts.extend(["## Plan", "", phase.output, ""])
        elif phase.name == "gate":
            parts.extend(["## Quality gate", "", phase.output, ""])

    parts.append("---")
    parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")
    return "\n".join(parts)
