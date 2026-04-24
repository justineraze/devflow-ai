"""Post-merge cleanup orchestration — `devflow sync`."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

from devflow.core.models import DirtyWorktreeError, SyncResult


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
    from devflow.integrations.git import branch_name

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
) -> SyncResult:
    """Orchestrate post-merge cleanup.

    Steps:
    1. Refuse to run if the working tree is dirty.
    2. ``git switch main && git pull --ff-only``
    3. ``git fetch -p`` to prune stale remote-tracking branches.
    4. Delete local branches whose upstream is gone (squash-merged).
    5. Unless *keep_artifacts*: archive features whose PR is merged.

    Args:
        project_root: Root of the git repo. Defaults to ``Path.cwd()``.
        dry_run: Print what would happen without mutating anything.
        keep_artifacts: Skip step 5 (archiving).

    Returns:
        A :class:`SyncResult` describing all actions taken.

    Raises:
        DirtyWorktreeError: If the working tree has uncommitted changes.
    """
    from devflow.core.artifacts import archive_feature
    from devflow.core.workflow import load_state, save_state
    from devflow.integrations.git import (
        delete_branch,
        fetch_prune,
        get_gone_branches,
        is_worktree_dirty,
        switch_and_pull_main,
    )

    cwd = project_root or Path.cwd()
    result = SyncResult(dry_run=dry_run)

    # Step 1 — dirty check.
    if is_worktree_dirty(cwd):
        raise DirtyWorktreeError(
            "Working tree has uncommitted changes. Commit or stash before syncing."
        )

    # Step 2 — switch base branch + pull.
    from devflow.core.config import load_config

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

    # Step 5 — archive features with merged PRs.
    if not keep_artifacts:
        state = load_state(cwd)
        from devflow.core.models import FeatureStatus
        done_features = [
            f for f in state.features.values()
            if f.status == FeatureStatus.DONE and not f.metadata.archived
        ]
        for feat in done_features:
            if _pr_is_merged(feat.id, cwd):
                if dry_run:
                    result.actions.append(f"would archive feature: {feat.id}")
                else:
                    # Artifacts may already be gone — still mark archived.
                    with contextlib.suppress(FileNotFoundError):
                        archive_feature(feat.id, cwd)
                    feat.metadata.archived = True
                    result.actions.append(f"archived feature: {feat.id}")
                result.features_archived.append(feat.id)

        if not dry_run and result.features_archived:
            save_state(state, cwd)

    result.current_branch = _current_branch(cwd)
    return result
