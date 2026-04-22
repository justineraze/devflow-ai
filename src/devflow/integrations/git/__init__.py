"""Git integrations — facade module.

Split into focused submodules; re-exports preserved for existing consumers.
"""
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
    delete_branch,
    detect_base_branch,
    fetch_prune,
    get_branch_diff_summary,
    get_diff_stat,
    get_gone_branches,
    get_untracked_files,
    has_commits_ahead,
    is_worktree_dirty,
    persist_files_summary,
    switch_and_pull_main,
    switch_branch,
)

__all__ = [
    "DiffSummary",
    "branch_name",
    "build_commit_message",
    "build_pr_title",
    "commit_changes",
    "create_branch",
    "delete_branch",
    "detect_base_branch",
    "fetch_prune",
    "get_branch_diff_summary",
    "get_diff_stat",
    "get_gone_branches",
    "get_untracked_files",
    "has_commits_ahead",
    "is_worktree_dirty",
    "persist_files_summary",
    "push_and_create_pr",
    "switch_and_pull_main",
    "switch_branch",
    "build_pr_body",
    "parse_plan_changes",
    "parse_plan_summary",
]
