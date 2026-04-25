"""Git integrations — public façade.

Exposes only the high-level operations the build loop, sync, and CLI
need.  Internal helpers (numstat parsing, regex-based predicates, raw
porcelain output…) live in submodules and must be imported from there
directly when needed in tests.

Note: ``collect_phase_result`` and ``persist_files_summary`` were moved
to :mod:`devflow.orchestration.phase_artifacts` because they bridge git
output and domain concerns (PhaseResult, CRITICAL_PATH_PATTERNS) —
keeping them here would create an integrations→core coupling that
should not exist.
"""

from __future__ import annotations

from .commit_message import build_commit_message, build_pr_title
from .pr_body import build_pr_body, push_and_create_pr
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
    get_orphan_feature_branches,
    get_untracked_files,
    is_worktree_dirty,
    main_repo_root,
    push_branch,
    remove_worktree,
    switch_and_pull_main,
    switch_branch,
)
from .smart_messages import (
    generate_commit_message,
    generate_feature_title,
    generate_pr_body,
    generate_pr_title,
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
    "generate_pr_title",
    "get_branch_diff_summary",
    "get_diff_stat",
    "get_fix_commit_log",
    "get_gone_branches",
    "get_head_sha",
    "get_orphan_feature_branches",
    "get_untracked_files",
    "is_worktree_dirty",
    "main_repo_root",
    "push_and_create_pr",
    "push_branch",
    "remove_worktree",
    "switch_and_pull_main",
    "switch_branch",
]
