"""Devflow error hierarchy — one root, typed children per concern.

Centralising the hierarchy lets callers catch :class:`DevflowError` at
the CLI boundary and turn it into an exit code without a giant
``except Exception`` clause that hides bugs.

Each concern raises its own subtype so handlers can react precisely:

- :class:`BackendError` — backend (Claude, etc.) failed in a way the
  caller cannot recover from (CLI not found, repeated timeouts).
- :class:`GateError` — quality gate could not run (tool missing,
  config invalid).  A *failing* gate is reported via ``GateReport.passed``
  and is **not** an exception.
- :class:`GitError` — git command failed unexpectedly (worktree dirty,
  branch creation failed, push rejected).
- :class:`DirtyWorktreeError` (in :mod:`devflow.core.sync_results`) and
  :class:`LinearError` (in :mod:`devflow.integrations.linear.client`)
  also inherit from :class:`DevflowError`.
"""

from __future__ import annotations


class DevflowError(Exception):
    """Root of devflow's typed exception hierarchy."""


class BackendError(DevflowError):
    """The AI backend failed in an unrecoverable way."""


class GateError(DevflowError):
    """The quality gate could not run (tooling missing or misconfigured)."""


class GitError(DevflowError):
    """A git command failed unexpectedly."""


class FeatureNotFoundError(DevflowError):
    """Raised when a feature ID is not present in the project state."""


class FeatureAlreadyDoneError(DevflowError):
    """Raised when ``resume`` targets a feature that has already finished."""


class FeatureNotFailedError(DevflowError):
    """Raised when ``retry`` is invoked on a feature that is not FAILED."""


__all__ = [
    "BackendError",
    "DevflowError",
    "FeatureAlreadyDoneError",
    "FeatureNotFailedError",
    "FeatureNotFoundError",
    "GateError",
    "GitError",
]
