"""Post-merge cleanup orchestration — `devflow sync`."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

from devflow.core.artifacts import archive_feature
from devflow.core.config import load_config
from devflow.core.models import Feature, FeatureStatus
from devflow.core.sync_results import DirtyWorktreeError as DirtyWorktreeError
from devflow.core.sync_results import SyncResult
from devflow.core.workflow import load_state, mutate_feature, save_state
from devflow.integrations.git import (
    branch_name,
    delete_branch,
    fetch_prune,
    get_gone_branches,
    get_orphan_feature_branches,
    is_worktree_dirty,
    remove_worktree,
    switch_and_pull_main,
)


def _current_branch(cwd: Path) -> str:
    """Return the name of the currently checked-out branch."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=str(cwd), timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _pr_is_merged(feature_id: str, cwd: Path) -> bool:
    """Return True if the PR associated with *feature_id* is merged.

    Uses ``gh pr view`` on the feature's branch.
    Returns False when the branch has no PR or the PR is not merged.
    """
    branch = branch_name(feature_id)
    result = subprocess.run(
        ["gh", "pr", "view", branch, "--json", "state", "--jq", ".state"],
        capture_output=True, text=True, cwd=str(cwd), timeout=60,
    )
    if result.returncode != 0:
        return False
    return result.stdout.strip().upper() == "MERGED"


def run_sync(
    project_root: Path | None = None,
    dry_run: bool = False,
    keep_artifacts: bool = False,
    prune_orphans: bool = False,
) -> SyncResult:
    """Orchestrate post-merge cleanup.

    Steps:
    1. Refuse to run if the working tree is dirty.
    2. ``git switch main && git pull --ff-only``
    3. ``git fetch -p`` to prune stale remote-tracking branches.
    4. Delete local branches whose upstream is gone (squash-merged).
    5. If *prune_orphans*: also delete local ``feat/*`` branches with
       zero commits ahead of the base branch (orphans left by rejected
       plans).  **Destructive** — opt-in only.
    6. Unless *keep_artifacts*: archive features whose PR is merged.

    Args:
        project_root: Root of the git repo. Defaults to ``Path.cwd()``.
        dry_run: Print what would happen without mutating anything.
        keep_artifacts: Skip step 6 (archiving).
        prune_orphans: Also delete orphan ``feat/*`` branches (step 5).

    Returns:
        A :class:`SyncResult` describing all actions taken.

    Raises:
        DirtyWorktreeError: If the working tree has uncommitted changes.
    """
    cwd = project_root or Path.cwd()
    result = SyncResult(dry_run=dry_run)

    # Step 1 — dirty check.
    if is_worktree_dirty(cwd):
        raise DirtyWorktreeError(
            "✗ Working tree has uncommitted changes — sync requires a clean tree"
            " — Fix: git stash or git commit before running devflow sync"
        )

    # Step 2 — switch base branch + pull.
    main = load_config(cwd).base_branch
    if dry_run:
        result.actions.append(f"would: git switch {main} && git pull --ff-only")
    else:
        switch_and_pull_main(main, cwd=cwd)

    # Step 3 — fetch -p.
    if dry_run:
        result.actions.append("would: git fetch -p")
    else:
        fetch_prune(cwd=cwd)

    # Step 4 — delete gone branches.
    gone = get_gone_branches(cwd)
    for branch in gone:
        if dry_run:
            result.actions.append(f"would delete branch: {branch}")
        else:
            if delete_branch(branch, cwd=cwd):
                result.actions.append(f"deleted branch: {branch}")
        result.branches_deleted.append(branch)

    # Step 5 — delete orphan feat/* branches (opt-in, destructive).
    if prune_orphans:
        orphans = get_orphan_feature_branches(base_branch=main, cwd=cwd)
        # Skip branches already removed in step 4 to avoid duplicates.
        orphans = [b for b in orphans if b not in result.branches_deleted]
        for branch in orphans:
            if dry_run:
                result.actions.append(f"would delete orphan branch: {branch}")
            else:
                if delete_branch(branch, cwd=cwd):
                    result.actions.append(f"deleted orphan branch: {branch}")
            result.branches_deleted.append(branch)

    # Step 6 — archive features with merged PRs.
    if not keep_artifacts:
        state = load_state(cwd)
        done_features = [
            f for f in state.features.values()
            if f.status == FeatureStatus.DONE and not f.metadata.archived
        ]

        def _archive_one(feat: Feature) -> None:
            """Check PR status and archive a single feature."""
            if _pr_is_merged(feat.id, cwd):
                if dry_run:
                    result.actions.append(f"would archive feature: {feat.id}")
                else:
                    with contextlib.suppress(FileNotFoundError):
                        archive_feature(feat.id, cwd)
                    feat.metadata.archived = True
                    result.actions.append(f"archived feature: {feat.id}")
                result.features_archived.append(feat.id)

        if done_features:
            from devflow.core.console import is_quiet

            if is_quiet() or dry_run or len(done_features) < 2:
                for feat in done_features:
                    _archive_one(feat)
            else:
                from rich.progress import (
                    MofNCompleteColumn,
                    Progress,
                    SpinnerColumn,
                    TextColumn,
                )

                from devflow.core.console import console as sync_console

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold]{task.description}"),
                    MofNCompleteColumn(),
                    console=sync_console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("Checking PRs...", total=len(done_features))
                    for feat in done_features:
                        _archive_one(feat)
                        progress.update(task, advance=1, description=f"Checking {feat.id}")

        if not dry_run and result.features_archived:
            save_state(state, cwd)

    # Step 7 — clean up orphan worktrees (DONE/archived features).
    if keep_artifacts:
        state = load_state(cwd)
    for feat in state.features.values():
        if feat.metadata.worktree_path is None:
            continue
        if feat.status != FeatureStatus.DONE and not feat.metadata.archived:
            continue
        if dry_run:
            result.actions.append(f"would remove worktree: {feat.id}")
        else:
            remove_worktree(feat.id, cwd=cwd)
            with mutate_feature(feat.id, cwd) as tracked:
                if tracked:
                    tracked.metadata.worktree_path = None
            result.actions.append(f"removed worktree: {feat.id}")

    result.current_branch = _current_branch(cwd)
    return result
