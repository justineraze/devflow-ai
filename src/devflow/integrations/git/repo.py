"""Git operations — branch management, commits, and diff utilities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TypedDict


class DiffSummary(TypedDict):
    """Structured summary of diff statistics between two refs."""

    lines_added: int
    lines_removed: int
    files_changed: int
    paths: list[str]


def _git(
    *args: str,
    cwd: Path | None = None,
    timeout: float = 30,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Low-level git subprocess wrapper with consistent defaults."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or Path.cwd()),
        timeout=timeout,
        check=check,
    )


def branch_name(feature_id: str) -> str:
    """Return the git branch name for a feature ID.

    Strips the redundant ``feat-`` prefix from the ID so we get
    ``feat/add-caching-0415`` instead of ``feat/feat-add-caching-0415``.
    """
    slug = feature_id.removeprefix("feat-")
    return f"feat/{slug}"


def create_branch(feature_id: str) -> str:
    """Create and checkout a git branch for the feature.

    If the branch already exists, switches to it instead.
    Returns the branch name.
    """
    branch = branch_name(feature_id)

    result = _git("checkout", "-b", branch)
    if result.returncode != 0:
        _git("checkout", branch)
    return branch


def switch_branch(branch: str) -> None:
    """Switch to an existing branch."""
    _git("checkout", branch)


def commit_changes(message: str) -> bool:
    """Stage all files and commit if there are changes.

    Returns True if a commit was created, False if nothing to commit.
    """
    _git("add", "-A")
    diff = _git("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return False

    _git("commit", "-m", message)
    return True


def has_commits_ahead(base_branch: str = "main") -> bool:
    """Check if current branch has commits ahead of base_branch."""
    result = _git("rev-list", "--count", f"{base_branch}..HEAD")
    return result.stdout.strip() != "0"


def get_diff_stat() -> str:
    """Return git diff --stat of the latest commit."""
    result = _git("diff", "--stat", "HEAD~1")
    return result.stdout.strip()


def get_branch_diff_summary(base_branch: str = "main") -> DiffSummary:
    """Summarize changes between current branch and *base_branch*.

    Returns ``{lines_added, lines_removed, files_changed, paths}``. Falls
    back to zero counters when git is unavailable or the base branch
    cannot be resolved (e.g. inside test sandboxes without a repo).
    """
    empty: DiffSummary = {
        "lines_added": 0,
        "lines_removed": 0,
        "files_changed": 0,
        "paths": [],
    }

    result = _git("diff", "--numstat", f"{base_branch}...HEAD")
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


def is_worktree_dirty(cwd: Path | None = None) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = _git("status", "--porcelain", cwd=cwd)
    return bool(result.stdout.strip())


def switch_and_pull_main(main_branch: str = "main", cwd: Path | None = None) -> None:
    """Switch to *main_branch* and fast-forward pull."""
    _git("switch", main_branch, cwd=cwd)
    _git("pull", "--ff-only", cwd=cwd, timeout=120)


def fetch_prune(cwd: Path | None = None) -> None:
    """Fetch from origin and prune stale remote-tracking branches."""
    _git("fetch", "-p", cwd=cwd, timeout=120)


def get_gone_branches(cwd: Path | None = None) -> list[str]:
    """Return local branch names whose upstream remote has been deleted.

    Parses ``git branch -vv`` looking for ``[<remote>/<branch>: gone]``.
    Returns an empty list if git is unavailable or there are no gone branches.
    """
    result = _git("branch", "-vv", cwd=cwd)
    if result.returncode != 0:
        return []

    gone: list[str] = []
    for line in result.stdout.splitlines():
        # Strip leading "* " or "  ".
        stripped = line.lstrip("* ").lstrip()
        # Branch name is the first token.
        parts = stripped.split()
        if not parts:
            continue
        branch = parts[0]
        # Look for the [gone] marker anywhere in the line.
        if re.search(r"\[.*: gone\]", line):
            gone.append(branch)
    return gone


def delete_branch(name: str, cwd: Path | None = None) -> bool:
    """Force-delete a local branch. Returns True on success."""
    result = _git("branch", "-D", name, cwd=cwd)
    return result.returncode == 0
