"""Unified registry for backends and trackers.

Backends are registered built-in (``claude``, ``pi`` in Phase C).
Trackers are discovered via ``importlib.metadata.entry_points``
(group ``devflow.trackers``), with Linear registered built-in.

Boot sequence: ``cli.py`` calls ``init_registry()`` at command entry.
Consumers use ``get_backend()`` and ``get_tracker()`` to access the
active instances.
"""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from devflow.core.backend import Backend
    from devflow.core.tracker import IssueTracker

_log = structlog.get_logger(__name__)

# ── Backend registry ─────────────────────────────────────────────────

_backends: dict[str, Backend] = {}
_active_backend: str | None = None


def register_backend(name: str, backend: Backend) -> None:
    """Register a backend under *name* (e.g. 'claude')."""
    _backends[name] = backend


def get_backend(name: str | None = None) -> Backend:
    """Return a backend by name, or the active default.

    Raises ``RuntimeError`` if no backend is registered or *name* is unknown.
    """
    target = name or _active_backend
    if target is None:
        raise RuntimeError(
            "✗ No backend registered — the build loop needs a backend"
            " — Fix: call devflow install or pass --backend claude"
        )
    if target not in _backends:
        available = ", ".join(sorted(_backends)) or "(none)"
        raise RuntimeError(
            f"✗ Unknown backend {target!r} — available: {available}"
            " — Fix: use --backend claude or --backend pi"
        )
    return _backends[target]


def set_active_backend(name: str) -> None:
    """Set the active backend by name."""
    global _active_backend  # noqa: PLW0603
    if name not in _backends:
        available = ", ".join(sorted(_backends)) or "(none)"
        raise RuntimeError(
            f"✗ Cannot activate unknown backend {name!r} — available: {available}"
            " — Fix: use --backend claude or --backend pi"
        )
    _active_backend = name


def list_backends() -> list[str]:
    """Return registered backend names."""
    return sorted(_backends)


# ── Tracker registry ─────────────────────────────────────────────────

_trackers: dict[str, IssueTracker] = {}
_active_tracker: str | None = None


def register_tracker(name: str, tracker: IssueTracker) -> None:
    """Register a tracker under *name* (e.g. 'linear')."""
    _trackers[name] = tracker


def get_tracker(name: str | None = None) -> IssueTracker | None:
    """Return a tracker by name, the active default, or None.

    Unlike ``get_backend()``, trackers are optional — returns ``None``
    when no tracker is configured rather than raising.
    """
    target = name or _active_tracker
    if target is None:
        return None
    return _trackers.get(target)


def set_active_tracker(name: str) -> None:
    """Set the active tracker by name."""
    global _active_tracker  # noqa: PLW0603
    if name not in _trackers:
        available = ", ".join(sorted(_trackers)) or "(none)"
        raise RuntimeError(
            f"✗ Unknown tracker {name!r} — available: {available}"
            " — Fix: check your config.yaml tracker settings"
        )
    _active_tracker = name


def list_trackers() -> list[str]:
    """Return registered tracker names."""
    return sorted(_trackers)


def discover_trackers() -> None:
    """Load tracker plugins from ``devflow.trackers`` entry points."""
    eps = importlib.metadata.entry_points(group="devflow.trackers")
    for ep in eps:
        if ep.name in _trackers:
            continue
        try:
            factory = ep.load()
            tracker = factory()
            register_tracker(ep.name, tracker)
            _log.debug("Discovered tracker plugin: %s", ep.name)
        except Exception:
            _log.warning("Failed to load tracker plugin: %s", ep.name, exc_info=True)


# ── Reset (test teardown) ───────────────────────────────────────────


def clear_registry() -> None:
    """Reset the entire registry. Intended for test teardown."""
    global _active_backend, _active_tracker  # noqa: PLW0603
    _backends.clear()
    _trackers.clear()
    _active_backend = None
    _active_tracker = None
