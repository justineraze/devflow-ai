"""Result types for ``devflow sync`` post-merge cleanup."""

from __future__ import annotations

from dataclasses import dataclass, field

from devflow.core.errors import DevflowError


class DirtyWorktreeError(DevflowError):
    """Raised when the working tree has uncommitted changes."""


@dataclass
class SyncResult:
    """Summary of what ``run_sync`` did (or would do in dry-run mode)."""

    branches_deleted: list[str] = field(default_factory=list)
    features_archived: list[str] = field(default_factory=list)
    current_branch: str = ""
    dry_run: bool = False
    actions: list[str] = field(default_factory=list)
    """Human-readable log of actions (populated in dry-run, also in real mode)."""


__all__ = ["DirtyWorktreeError", "SyncResult"]
