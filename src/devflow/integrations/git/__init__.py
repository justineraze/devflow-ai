"""Git integrations — facade module.

Split into focused submodules; re-exports preserved for existing consumers.

Note: ``collect_phase_result`` and ``persist_files_summary`` were moved to
``devflow.orchestration.phase_artifacts`` because they bridge git output
and domain concerns (PhaseResult, CRITICAL_PATH_PATTERNS) — keeping them
here would create an integrations→core coupling that should not exist.
"""

from __future__ import annotations

from .commit_message import build_commit_message, build_pr_title
from .pr_body import (
    build_pr_body,
    parse_plan_changes,
    parse_plan_summary,
    push_and_create_pr,
)
from .repo import (
    DiffSummary,
    branch_name,
    commit_changes,
    create_branch,
    create_worktree,
    delete_branch,
    detect_base_branch,
    fetch_prune,
    get_branch_diff_summary,
    get_diff_stat,
    get_fix_commit_log,
    get_gone_branches,
    get_head_sha,
    get_untracked_files,
    git_log_numstat,
    git_status_porcelain,
    has_commits_ahead,
    is_worktree_dirty,
    list_worktrees,
    main_repo_root,
    push_branch,
    remove_worktree,
    reset_to_sha,
    revert_head,
    switch_and_pull_main,
    switch_branch,
)
from .smart_messages import (
    generate_commit_message,
    generate_feature_title,
    generate_pr_body,
)

__all__ = [
    "DiffSummary",
    "branch_name",
    "build_commit_message",
    "build_pr_body",
    "build_pr_title",
    "commit_changes",
    "create_branch",
    "create_worktree",
    "delete_branch",
    "detect_base_branch",
    "fetch_prune",
    "generate_commit_message",
    "generate_feature_title",
    "generate_pr_body",
    "get_branch_diff_summary",
    "get_diff_stat",
    "get_fix_commit_log",
    "get_gone_branches",
    "get_head_sha",
    "get_untracked_files",
    "git_log_numstat",
    "git_status_porcelain",
    "has_commits_ahead",
    "is_worktree_dirty",
    "list_worktrees",
    "main_repo_root",
    "parse_plan_changes",
    "parse_plan_summary",
    "push_and_create_pr",
    "push_branch",
    "remove_worktree",
    "reset_to_sha",
    "revert_head",
    "switch_and_pull_main",
    "switch_branch",
]
