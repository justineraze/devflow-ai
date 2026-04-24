"""Build event callbacks — decouples orchestration from UI rendering.

The build loop fires events (phase start, success, failure, gate result,
summary) without knowing *how* they are rendered.  ``cli.py`` wires up
concrete renderers from ``ui/``; tests can pass silent no-ops.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devflow.core.metrics import BuildTotals, PhaseMetrics, PhaseResult
    from devflow.core.models import Feature


def _noop(*_args: object, **_kwargs: object) -> None:  # noqa: ARG001
    """Default no-op callback."""


@dataclass
class BuildCallbacks:
    """Event callbacks fired by the build loop.

    Every field defaults to a no-op so callers only need to supply the
    callbacks they care about (e.g. tests can omit all of them).
    """

    on_banner: Callable[[Feature, str, str | None], None] = field(
        default=_noop,
    )
    on_phase_header: Callable[[int, int, str, str], None] = field(
        default=_noop,
    )
    on_phase_success: Callable[[str, float, PhaseMetrics], None] = field(
        default=_noop,
    )
    on_phase_failure: Callable[[str, float, str], None] = field(
        default=_noop,
    )
    on_phase_auto_retry: Callable[[str, float, str], None] = field(
        default=_noop,
    )
    on_phase_commits: Callable[[PhaseResult], None] = field(
        default=_noop,
    )
    on_gate_panel: Callable[[str, Path | None], None] = field(
        default=_noop,
    )
    on_build_summary: Callable[
        [Feature, BuildTotals, str | None, str, float | None], None
    ] = field(default=_noop)
