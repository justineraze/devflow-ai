"""Build event callbacks — decouples orchestration from UI rendering.

The build loop fires events (phase start, success, failure, gate result,
summary) without knowing *how* they are rendered.  ``cli.py`` wires up
concrete renderers from ``ui/``; tests can pass silent no-ops.

Two responsibilities are kept separate (Interface Segregation Principle):

- :class:`BuildEventListener` — fire-and-forget notifications.  Defaults
  are silent no-ops so tests don't need to wire them.
- :class:`BuildPrompter` — *interactive* questions (e.g. plan
  confirmation).  Has **no** silent default: callers must inject a
  concrete prompter.  This prevents accidentally auto-approving a plan
  in CI just because the test forgot to pass one.

:class:`BuildCallbacks` is a backward-compatible bundle of both.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from devflow.core.metrics import BuildTotals, PhaseMetrics, PhaseResult, ToolUse
    from devflow.core.models import Feature

# Type alias: factory yielding a per-tool callback for one phase run.
# Callers (the runner) wrap their backend.execute() call in
# ``with factory(phase_name) as on_tool:`` and forward on_tool to the
# backend.  The default factory yields ``None`` — runner short-circuits
# and no UI updates fire.
PhaseToolListenerFactory = Callable[
    [str], AbstractContextManager["Callable[[ToolUse], None] | None"],
]


def _silent_phase_listener(_phase_name: str) -> AbstractContextManager[None]:
    """Default factory: yields ``None`` so the runner skips UI updates."""
    return contextlib.nullcontext(None)


def _noop(*_args: object, **_kwargs: object) -> None:  # noqa: ARG001
    """Default no-op callback."""


class BuildPrompter(Protocol):
    """Interactive prompts during a build — must be supplied by callers."""

    def confirm_plan(
        self, plan_output: str, feature_id: str, create_pr: bool,
    ) -> bool:
        """Show *plan_output* and ask whether to proceed.

        Returns True to proceed, False to pause the build.
        """
        ...


class _AutoApprovePrompter:
    """Test-only prompter that always approves.  Must be passed explicitly."""

    def confirm_plan(self, _plan: str, _feat: str, _pr: bool) -> bool:  # noqa: PLR6301
        return True


AUTO_APPROVE: BuildPrompter = _AutoApprovePrompter()
"""Sentinel auto-approver for tests — pass explicitly, never the default.

Production code should always inject a real prompter (e.g. the Rich
confirmation renderer) so a developer can intervene.
"""


@dataclass
class BuildEventListener:
    """Fire-and-forget events emitted by the build loop.

    Every field defaults to a silent no-op so tests only need to supply
    the events they care about.  Callers wire concrete UI renderers via
    :func:`devflow.cli._build_callbacks`.
    """

    on_banner: Callable[[Feature, str, str | None], None] = field(default=_noop)
    on_do_banner: Callable[[Feature], None] = field(default=_noop)
    """Banner shown for ``devflow do`` (no PR mode)."""

    on_resume_notice: Callable[[str], None] = field(default=_noop)
    """Notice when a build resumes with feedback."""

    on_phase_header: Callable[[int, int, str, str], None] = field(default=_noop)
    on_phase_success: Callable[[str, float, PhaseMetrics], None] = field(default=_noop)
    on_phase_failure: Callable[[str, float, str], None] = field(default=_noop)
    on_phase_auto_retry: Callable[[str, float, str], None] = field(default=_noop)
    on_phase_commits: Callable[[PhaseResult], None] = field(default=_noop)
    on_gate_panel: Callable[[str, Path | None], None] = field(default=_noop)
    on_build_summary: Callable[
        [Feature, BuildTotals, str | None, str, float | None], None
    ] = field(default=_noop)

    on_pr_creating: Callable[[], None] = field(default=_noop)
    """Fired right before push_and_create_pr() — UI may show a status line."""

    on_pr_failed: Callable[[], None] = field(default=_noop)
    """Fired when ``gh pr create`` failed; user must push manually."""

    on_low_cache_warning: Callable[[float], None] = field(default=_noop)
    """Fired when the average cache hit rate of the last 3 builds drops."""

    on_epic_complete: Callable[[str], None] = field(default=_noop)
    """Fired when a feature completes the last sub-feature of an epic."""

    on_revert_hint: Callable[[str, str], None] = field(default=_noop)
    """``devflow do`` failure hint: arguments are ``(feature_id, initial_sha)``."""

    on_do_success: Callable[[str, str], None] = field(default=_noop)
    """``devflow do`` success: arguments are ``(current_sha, initial_sha)``."""

    phase_tool_listener: PhaseToolListenerFactory = field(
        default=_silent_phase_listener,
    )
    """Factory yielding a per-tool callback for each phase execution.

    The runner wraps ``backend.execute()`` in
    ``with factory(phase_name) as on_tool: ...``.  The CLI plugs in a
    Rich spinner; tests use the silent default which yields ``None``
    and skips UI updates entirely — no UI imports leak into the
    orchestration layer.
    """


@dataclass
class BuildCallbacks(BuildEventListener):
    """Convenience bundle: events + prompter passed to the build loop.

    Production callers typically construct one of these via
    :func:`devflow.cli._build_callbacks`. Tests may use
    :data:`AUTO_APPROVE` as the prompter.
    """

    prompter: BuildPrompter = field(default=AUTO_APPROVE)

    def confirm_plan(
        self, plan_output: str, feature_id: str, create_pr: bool,
    ) -> bool:
        """Delegate to the injected prompter."""
        return self.prompter.confirm_plan(plan_output, feature_id, create_pr)
