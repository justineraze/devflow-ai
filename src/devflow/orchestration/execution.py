"""Execution loop — runs implementation, review, gate, and fixing phases.

Extracted from build.py. The planning loop lives in planning.py;
post-phase dispatch lives in phase_handlers.py.
"""

from __future__ import annotations

import time
from pathlib import Path

from devflow.core.backend import get_backend
from devflow.core.metrics import BuildTotals
from devflow.core.models import Feature, PhaseStatus
from devflow.core.workflow import load_state
from devflow.integrations import git
from devflow.orchestration.events import BuildCallbacks
from devflow.orchestration.model_routing import get_phase_agent, resolve_model
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    run_phase,
)
from devflow.orchestration.phase_handlers import (
    PostPhaseCtx,
    dispatch_on_failure,
    dispatch_post_phase_success,
    maybe_re_review,
)
from devflow.orchestration.planning import _execute_phase


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


def run_execution_loop(
    feature: Feature,
    totals: BuildTotals,
    initial_untracked: list[str],
    stack: str | None,
    callbacks: BuildCallbacks,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    base_sha: str = "",
    cwd: Path | None = None,
) -> tuple[Feature, bool]:
    """Run implementation, review, gate, and fixing phases.

    When *cwd* is set (worktree mode), phases execute in that directory
    instead of the current working directory.
    """
    total = len(feature.phases)

    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        done_count = sum(1 for p in feature.phases if p.status == PhaseStatus.DONE)
        phase_num = done_count + 1
        agent_name = get_phase_agent(feature, phase.name, base, stack=stack)

        tier = resolve_model(feature, phase)
        model_label = get_backend().model_name(tier)
        callbacks.on_phase_header(phase_num, total, phase.name, model_label)

        pre_phase_sha = git.get_head_sha(short=False)

        start = time.monotonic()
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, base_sha=base_sha,
            stack=stack,
            phase_tool_listener=callbacks.phase_tool_listener,
            cwd=cwd,
        )
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)
            dispatch_post_phase_success(
                feature, phase, pre_phase_sha, output, metrics,
                elapsed, model_label, initial_untracked, totals, callbacks,
                base, base_branch,
            )

            updated = maybe_re_review(feature, phase, output, base)
            if updated is not None:
                feature = updated
                total = len(feature.phases)
                continue
        else:
            ctx = PostPhaseCtx(
                feature=feature, phase=phase, output=output, metrics=metrics,
                elapsed=elapsed, model_label=model_label,
                pre_phase_sha=pre_phase_sha,
                initial_untracked=initial_untracked,
                totals=totals, callbacks=callbacks,
                base=base, base_branch=base_branch,
            )
            feature, should_retry = dispatch_on_failure(ctx)
            if should_retry:
                continue

            fail_phase(feature.id, phase.name, output, base)
            callbacks.on_phase_failure(phase.name, elapsed, output)
            return feature, False

        feature = _refresh_feature(feature.id, base) or feature

    return feature, True
