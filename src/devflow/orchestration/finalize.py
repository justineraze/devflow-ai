"""Build finalization — PR creation, metrics persistence, cache warnings.

Extracted from build.py to keep the orchestrator focused on wiring.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.epics import check_epic_completion
from devflow.core.history import (
    append_build_metrics,
    build_metrics_from,
    read_history,
)
from devflow.core.metrics import BuildTotals
from devflow.core.models import Feature
from devflow.core.workflow import load_state
from devflow.integrations import git
from devflow.orchestration.events import BuildCallbacks
from devflow.orchestration.phase_exec import sync_linear_if_configured

_LOW_CACHE_THRESHOLD = 0.4
_CACHE_WARNING_WINDOW = 3


def _maybe_warn_low_cache(callbacks: BuildCallbacks, base: Path | None) -> None:
    """Fire on_low_cache_warning when recent builds drop under the threshold."""
    recent = read_history(base, limit=_CACHE_WARNING_WINDOW)
    if len(recent) < _CACHE_WARNING_WINDOW:
        return
    avg_cache = sum(r.cache_hit_rate for r in recent) / _CACHE_WARNING_WINDOW
    if avg_cache < _LOW_CACHE_THRESHOLD:
        callbacks.on_low_cache_warning(avg_cache)


def finalize_build(
    feature: Feature,
    branch: str,
    totals: BuildTotals,
    initial_untracked: list[str],
    callbacks: BuildCallbacks,
    base: Path | None = None,
    base_branch: str = "main",
) -> bool:
    """Push branch, create PR, persist metrics, and render the build summary."""
    callbacks.on_pr_creating()

    state = load_state(base)
    final = state.get_feature(feature.id) or feature
    pr_url = git.push_and_create_pr(
        final, branch, exclude=initial_untracked, base_branch=base_branch,
    )

    record = build_metrics_from(final, totals, success=True)
    append_build_metrics(record, base)

    _maybe_warn_low_cache(callbacks, base)

    sync_linear_if_configured(final, base)

    callbacks.on_build_summary(final, totals, pr_url, branch, None)
    if pr_url is None:
        callbacks.on_pr_failed()

    if final.parent_id and check_epic_completion(final.parent_id, base):
        callbacks.on_epic_complete(final.parent_id)

    return True
