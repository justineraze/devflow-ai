"""Git operations — branch management, commits, and PR creation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from devflow.core.models import Feature, PhaseStatus
from devflow.ui.console import console

# Max length for PR titles and commit summaries (Conventional Commits best practice).
_MAX_LEN = 70


def _commit_prefix(feature: Feature) -> str:
    """Return the Conventional Commits prefix for a feature.

    ``fix:`` for the quick workflow (bug fixes), ``feat:`` otherwise.
    """
    return "fix" if feature.workflow == "quick" else "feat"


def _normalize_description(description: str) -> str:
    """Capitalize the first letter and strip trailing punctuation."""
    desc = description.strip().rstrip(".!?")
    if desc:
        desc = desc[0].upper() + desc[1:]
    return desc


def _truncate_at_word(text: str, max_len: int, min_prefix: int = 0) -> str:
    """Truncate text at the last word boundary within max_len."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > min_prefix:
        truncated = truncated[:last_space]
    return truncated


def build_commit_message(feature: Feature, suffix: str | None = None) -> str:
    """Build a standardized Conventional Commits message for a feature.

    Format:
        feat: Add caching layer                 (no suffix — used for PR title)
        feat: Add caching layer — implementing  (with suffix — intermediate commits)

    Args:
        feature: The feature this commit is for.
        suffix: Optional qualifier (e.g. "implementing", "fixing",
                "leftover changes"). Appended after an em-dash.
    """
    prefix = _commit_prefix(feature)
    desc = _normalize_description(feature.description)
    base = f"{prefix}: {desc}"

    if suffix:
        base = f"{base} — {suffix}"

    return _truncate_at_word(base, _MAX_LEN, min_prefix=len(prefix) + 2)


def build_pr_title(feature: Feature) -> str:
    """Build a Conventional Commits PR title (no suffix)."""
    return build_commit_message(feature)


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


def get_branch_diff_summary(base_branch: str = "main") -> dict[str, object]:
    """Summarize changes between current branch and *base_branch*.

    Returns ``{lines_added, lines_removed, files_changed, paths}``. Falls
    back to zero counters when git is unavailable or the base branch
    cannot be resolved (e.g. inside test sandboxes without a repo).
    """
    cwd = str(Path.cwd())
    empty: dict[str, object] = {
        "lines_added": 0,
        "lines_removed": 0,
        "files_changed": 0,
        "paths": [],
    }

    result = subprocess.run(
        ["git", "diff", "--numstat", f"{base_branch}...HEAD"],
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return empty

    added = 0
    removed = 0
    paths: list[str] = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, r, path = parts[0], parts[1], parts[2]
        # Binary files show "-" for counts.
        if a.isdigit():
            added += int(a)
        if r.isdigit():
            removed += int(r)
        paths.append(path)

    return {
        "lines_added": added,
        "lines_removed": removed,
        "files_changed": len(paths),
        "paths": paths,
    }


def push_and_create_pr(feature: Feature, branch: str) -> str | None:
    """Push branch and create a GitHub PR.

    Commits any uncommitted changes first as a safety net.
    Returns the PR URL, or None if creation failed.
    """
    cwd = str(Path.cwd())

    # Safety net: commit anything left uncommitted.
    commit_changes(build_commit_message(feature, suffix="leftover changes"))

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


def _build_pr_body(feature: Feature) -> str:
    """Build the PR description from phase outputs."""
    parts = ["## Summary", "", feature.description, ""]

    for phase in feature.phases:
        if phase.status != PhaseStatus.DONE or not phase.output:
            continue
        if phase.name == "planning":
            parts.extend(["## Plan", "", phase.output, ""])
        elif phase.name == "gate":
            parts.extend(["## Quality gate", "", phase.output, ""])

    parts.append("---")
    parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")
    return "\n".join(parts)
