"""Git integrations — facade module.

Split into focused submodules; re-exports preserved for existing consumers.
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
    collect_phase_result,
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
    has_commits_ahead,
    is_worktree_dirty,
    list_worktrees,
    main_repo_root,
    persist_files_summary,
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
    "build_pr_title",
    "collect_phase_result",
    "commit_changes",
    "create_branch",
    "create_worktree",
    "delete_branch",
    "detect_base_branch",
    "fetch_prune",
    "get_branch_diff_summary",
    "get_diff_stat",
    "get_fix_commit_log",
    "get_gone_branches",
    "get_head_sha",
    "get_untracked_files",
    "has_commits_ahead",
    "is_worktree_dirty",
    "list_worktrees",
    "main_repo_root",
    "persist_files_summary",
    "remove_worktree",
    "reset_to_sha",
    "revert_head",
    "push_and_create_pr",
    "switch_and_pull_main",
    "switch_branch",
    "build_pr_body",
    "generate_commit_message",
    "generate_feature_title",
    "generate_pr_body",
    "parse_plan_changes",
    "parse_plan_summary",
]
