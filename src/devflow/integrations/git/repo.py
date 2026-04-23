"""Git operations — branch management, commits, and diff utilities."""

from __future__ import annotations

import json
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


def main_repo_root(cwd: Path | None = None) -> Path:
    """Return the root of the main worktree (not a linked worktree).

    Uses ``git rev-parse --path-format=absolute --git-common-dir`` which
    resolves to the shared ``.git`` directory regardless of which worktree
    we are in. The parent of that directory is the main repo root.

    Falls back to ``git rev-parse --show-toplevel`` when the common-dir
    approach fails (e.g. bare repos or old git versions).
    """
    result = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    if result.returncode == 0:
        common = Path(result.stdout.strip())
        # common is e.g. /path/to/repo/.git — parent is the repo root.
        if common.name == ".git":
            return common.parent
    # Fallback.
    result = _git("rev-parse", "--show-toplevel", cwd=cwd)
    return Path(result.stdout.strip()) if result.returncode == 0 else (cwd or Path.cwd())


def create_worktree(feature_id: str, cwd: Path | None = None) -> tuple[str, Path]:
    """Create a git worktree for *feature_id* and return ``(branch, worktree_path)``.

    The worktree is placed in ``.devflow/.worktrees/<feature-slug>/``
    under the main repo root. The branch is created if it doesn't exist.
    """
    branch = branch_name(feature_id)
    root = main_repo_root(cwd)
    wt_dir = root / ".devflow" / ".worktrees" / feature_id
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    if wt_dir.exists():
        # Already created — just return it.
        return branch, wt_dir

    # Try creating with a new branch; fall back to existing branch.
    result = _git("worktree", "add", "-b", branch, str(wt_dir), cwd=cwd)
    if result.returncode != 0:
        _git("worktree", "add", str(wt_dir), branch, cwd=cwd, check=True)
    return branch, wt_dir


def remove_worktree(feature_id: str, cwd: Path | None = None) -> bool:
    """Remove the worktree for *feature_id*. Returns True on success."""
    root = main_repo_root(cwd)
    wt_dir = root / ".devflow" / ".worktrees" / feature_id
    if not wt_dir.exists():
        return True
    result = _git("worktree", "remove", "--force", str(wt_dir), cwd=cwd)
    return result.returncode == 0


def list_worktrees(cwd: Path | None = None) -> list[dict[str, str]]:
    """List all active worktrees as ``[{"path": ..., "branch": ...}]``."""
    result = _git("worktree", "list", "--porcelain", cwd=cwd)
    if result.returncode != 0:
        return []

    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
    if current:
        worktrees.append(current)
    return worktrees


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


def get_untracked_files(cwd: Path | None = None) -> list[str]:
    """Return the list of untracked files honoring .gitignore."""
    result = _git("ls-files", "--others", "--exclude-standard", cwd=cwd)
    return [line for line in result.stdout.splitlines() if line.strip()]


def commit_changes(message: str, exclude: list[str] | None = None) -> bool:
    """Stage changes and commit if any.

    When *exclude* is provided, paths in it are kept out of the staged set.
    This is how the build loop prevents user scratch files (prompt notes, temp
    drafts) that existed as untracked before the build started from being swept
    into devflow's auto-commits.
    """
    if exclude:
        pathspecs = [f":(exclude){p}" for p in exclude]
        _git("add", "-A", "--", ".", *pathspecs)
    else:
        _git("add", "-A")
    diff = _git("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return False

    _git("commit", "-m", message)
    return True


def detect_base_branch() -> str:
    """Auto-detect the default branch from the remote (origin).

    Parses ``git remote show origin`` for the HEAD branch line.
    Falls back to ``"main"`` when the remote is unreachable or
    the output doesn't match the expected format.
    """
    result = _git("remote", "show", "origin", timeout=10)
    if result.returncode != 0:
        return "main"
    for line in result.stdout.splitlines():
        if "HEAD branch:" in line:
            return line.split(":", 1)[1].strip()
    return "main"


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


def persist_files_summary(
    feature_id: str, base: Path | None = None, base_branch: str = "main",
) -> None:
    """Write files.json capturing the branch-diff summary for downstream phases.

    Enriches the raw diff summary with ``critical_paths`` — paths matching
    security/auth/payment patterns defined in ``CRITICAL_PATH_PATTERNS``.
    """
    from devflow.core.artifacts import write_artifact
    from devflow.core.models import CRITICAL_PATH_PATTERNS

    summary = get_branch_diff_summary(base_branch)
    paths = summary.get("paths") or []
    critical = [
        p for p in paths
        if any(pat in p.lower() for pat in CRITICAL_PATH_PATTERNS)
    ]
    summary["critical_paths"] = critical
    write_artifact(feature_id, "files.json", json.dumps(summary, indent=2), base)
