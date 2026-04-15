"""Git operations — branch management, commits, and PR creation."""

from __future__ import annotations

import re
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


def is_worktree_dirty(cwd: Path | None = None) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(cwd or Path.cwd()),
    )
    return bool(result.stdout.strip())


def switch_and_pull_main(main_branch: str = "main", cwd: Path | None = None) -> None:
    """Switch to *main_branch* and fast-forward pull."""
    root = str(cwd or Path.cwd())
    subprocess.run(
        ["git", "switch", main_branch],
        capture_output=True, text=True, cwd=root,
    )
    subprocess.run(
        ["git", "pull", "--ff-only"],
        capture_output=True, text=True, cwd=root,
    )


def fetch_prune(cwd: Path | None = None) -> None:
    """Fetch from origin and prune stale remote-tracking branches."""
    subprocess.run(
        ["git", "fetch", "-p"],
        capture_output=True, text=True, cwd=str(cwd or Path.cwd()),
    )


def get_gone_branches(cwd: Path | None = None) -> list[str]:
    """Return local branch names whose upstream remote has been deleted.

    Parses ``git branch -vv`` looking for ``[<remote>/<branch>: gone]``.
    Returns an empty list if git is unavailable or there are no gone branches.
    """
    result = subprocess.run(
        ["git", "branch", "-vv"],
        capture_output=True, text=True, cwd=str(cwd or Path.cwd()),
    )
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
        branch_name = parts[0]
        # Look for the [gone] marker anywhere in the line.
        if re.search(r"\[.*: gone\]", line):
            gone.append(branch_name)
    return gone


def delete_branch(name: str, cwd: Path | None = None) -> bool:
    """Force-delete a local branch. Returns True on success."""
    result = subprocess.run(
        ["git", "branch", "-D", name],
        capture_output=True, text=True, cwd=str(cwd or Path.cwd()),
    )
    return result.returncode == 0


def _parse_plan_summary(plan_output: str) -> str:
    """Extract the one-line summary from the plan header.

    Looks for: ``## Plan: <id> — <summary>``
    Supports em-dash (—), en-dash (–), and regular hyphen (-).
    Returns the summary text, or "" if the header is absent.
    """
    match = re.search(r"^##\s+Plan:[^\n]*[—–\-]\s*(.+)$", plan_output, re.MULTILINE)
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
    """Build the PR description from planning and gate phase outputs.

    Summary and Changes are extracted from the planner's structured output.
    Falls back to ``feature.description`` when the planning phase is absent
    (quick/fix workflows) or produced no parseable header.
    """
    plan_output = next(
        (p.output for p in feature.phases if p.name == "planning" and p.output),
        "",
    )

    summary = _parse_plan_summary(plan_output) if plan_output else ""
    changes = _parse_plan_changes(plan_output) if plan_output else ""

    parts = ["## Summary", ""]
    parts.append(summary or feature.description)
    parts.append("")

    if changes:
        parts.extend(["## Changes", "", changes, ""])

    for phase in feature.phases:
        if phase.name == "gate" and phase.status == PhaseStatus.DONE and phase.output:
            parts.extend(["## Quality gate", "", phase.output, ""])

    parts.append("---")
    parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")
    return "\n".join(parts)
