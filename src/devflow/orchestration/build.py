"""Build loop — executes a feature through its phases end-to-end.

Responsible for one thing: running the plan-first confirmation flow,
coordinating phase execution, and creating the PR on success.

Feature lifecycle (create/resume/retry) → lifecycle.py
Phase state machine (run/complete/fail) → phase_exec.py
Model selection                          → model_routing.py
Gate execution                           → integrations/gate/
Plan output parsing                      → plan_parser.py
Review cycle logic                       → review.py
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from devflow.core.artifacts import save_phase_output, write_artifact
from devflow.core.backend import get_backend
from devflow.core.config import load_config
from devflow.core.epics import check_epic_completion
from devflow.core.history import (
    append_build_metrics,
    build_metrics_from,
    read_history,
)
from devflow.core.metrics import BuildTotals, PhaseMetrics
from devflow.core.models import (
    Feature,
    PhaseName,
    PhaseRecord,
    PhaseStatus,
    PhaseType,
)
from devflow.core.phases import get_spec
from devflow.core.workflow import load_state, mutate_feature
from devflow.integrations import git
from devflow.integrations.gate import run_gate_phase
from devflow.integrations.git import branch_name, main_repo_root
from devflow.integrations.git.repo import git_status_porcelain
from devflow.integrations.git.smart_messages import generate_commit_message
from devflow.orchestration import runner
from devflow.orchestration.events import (
    BuildCallbacks,
    PhaseToolListenerFactory,
    _silent_phase_listener,
)
from devflow.orchestration.model_routing import get_phase_agent, resolve_model
from devflow.orchestration.phase_artifacts import (
    collect_phase_result,
    persist_files_summary,
)
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    reset_planning_phases,
    run_phase,
    setup_gate_retry,
    sync_linear_if_configured,
)
from devflow.orchestration.plan_parser import (
    parse_plan_module,
    parse_plan_title,
    parse_plan_type,
)
from devflow.orchestration.review import (
    setup_re_fix,
    setup_re_review,
    should_re_review,
)

if TYPE_CHECKING:
    from devflow.core.metrics import PhaseResult


# Average cache hit rate threshold below which a warning is fired.
_LOW_CACHE_THRESHOLD = 0.4

# How many recent builds to average for the cache warning.
_CACHE_WARNING_WINDOW = 3


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


def _execute_phase(
    feature: Feature, phase: PhaseRecord, agent_name: str,
    base: Path | None = None, verbose: bool = False,
    base_sha: str = "",
    stack: str | None = None,
    phase_tool_listener: PhaseToolListenerFactory = _silent_phase_listener,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via the backend or local gate."""
    if get_spec(phase.name).phase_type == PhaseType.GATE:
        return run_gate_phase(
            base, stack=stack,
            feature_id=feature.id, base_sha=base_sha,
        )
    return runner.execute_phase(
        feature, phase, agent_name, verbose=verbose,
        phase_tool_listener=phase_tool_listener,
    )


# ── Planning loop ─────────────────────────────────────────────────


def _persist_plan_metadata(feature_id: str, plan_output: str, base: Path | None) -> None:
    """Extract and save plan-derived metadata (scope, title, commit_type)."""
    module = parse_plan_module(plan_output)
    title = parse_plan_title(plan_output)
    commit_type = parse_plan_type(plan_output)
    if not (module or title or commit_type):
        return
    with mutate_feature(feature_id, base) as feat:
        if not feat:
            return
        if module:
            feat.metadata.scope = module
        if title:
            feat.metadata.title = title
        if commit_type:
            feat.metadata.commit_type = commit_type


def _run_planning_loop(
    feature: Feature,
    totals: BuildTotals,
    stack: str | None,
    callbacks: BuildCallbacks,
    base: Path | None = None,
    verbose: bool = False,
) -> tuple[Feature, str, bool]:
    """Run planning phases and return (feature, plan_output, success).

    Stops as soon as a non-planning phase is encountered (resetting it
    back to PENDING so the execution loop picks it up).
    """
    total = len(feature.phases)
    plan_output = ""
    phase_num = 0

    while True:
        phase = run_phase(feature, base)
        if not phase:
            break

        phase_num += 1
        agent_name = get_phase_agent(feature, phase.name, base, stack=stack)

        # Stop before non-planning phases — wait for confirmation.
        if get_spec(phase.name).phase_type != PhaseType.PLANNING:
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    p = tracked.find_phase(phase.name)
                    if p and p.status == PhaseStatus.IN_PROGRESS:
                        p.reset()
            break

        tier = resolve_model(feature, phase)
        model_label = get_backend().model_name(tier)
        callbacks.on_phase_header(phase_num, total, phase.name, model_label)
        start = time.monotonic()
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, stack=stack,
            phase_tool_listener=callbacks.phase_tool_listener,
        )
        elapsed = time.monotonic() - start

        if not success:
            totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
            fail_phase(feature.id, phase.name, output, base)
            callbacks.on_phase_failure(phase.name, elapsed, output)
            return feature, "", False

        complete_phase(feature.id, phase.name, output, base)
        callbacks.on_phase_success(phase.name, elapsed, metrics)
        totals.add(phase.name, metrics, elapsed, model=model_label)

        if phase.name == PhaseName.PLANNING:
            plan_output = output
            _persist_plan_metadata(feature.id, output, base)

        feature = _refresh_feature(feature.id, base) or feature

    return feature, plan_output, True


# ── Post-phase handlers ───────────────────────────────────────────


def _handle_post_phase_commit(
    feature: Feature,
    phase: PhaseRecord,
    pre_phase_sha: str,
    success: bool,
    output: str,
    metrics: PhaseMetrics,
    elapsed: float,
    model_label: str,
    initial_untracked: list[str],
    totals: BuildTotals,
    callbacks: BuildCallbacks,
    base: Path | None,
    base_branch: str,
) -> None:
    """Auto-commit after implementing/fixing and record metrics.

    Detects uncommitted changes with a single ``git status --porcelain``
    (cheap), commits them, then collects the full phase result exactly
    once.  The previous version called :func:`collect_phase_result`
    twice on every code phase, doubling the git log/numstat work.
    """
    if git_status_porcelain():
        msg = generate_commit_message(feature, phase=phase.name)
        # Return value (False = nothing actually committed because every
        # change matched *exclude*) is intentionally discarded: the
        # subsequent collect_phase_result picks up the real state
        # whether the commit happened or not.
        _ = git.commit_changes(msg, exclude=initial_untracked)

    phase_result = collect_phase_result(pre_phase_sha, success, output, metrics)

    callbacks.on_phase_success(phase.name, elapsed, metrics)
    callbacks.on_phase_commits(phase_result)
    totals.add(
        phase.name, metrics, elapsed, model=model_label,
        commits=len(phase_result.commits),
        files_changed=len(phase_result.files_changed),
        insertions=sum(c.insertions for c in phase_result.commits),
        deletions=sum(c.deletions for c in phase_result.commits),
    )

    _save_phase_commits_artifact(feature.id, phase.name, phase_result, base)
    persist_files_summary(feature.id, base, base_branch)


def _handle_gate_result(
    feature: Feature,
    phase: PhaseRecord,
    output: str,
    metrics: PhaseMetrics,
    elapsed: float,
    model_label: str,
    totals: BuildTotals,
    callbacks: BuildCallbacks,
    base: Path | None,
) -> tuple[Feature, bool]:
    """Handle a gate failure. Returns (feature, should_retry)."""
    totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
    save_phase_output(feature.id, "gate", output, base)
    if setup_gate_retry(feature.id, base):
        callbacks.on_gate_panel(feature.id, base)
        callbacks.on_phase_auto_retry(phase.name, elapsed, "")
        feature = _refresh_feature(feature.id, base) or feature
        return feature, True
    return feature, False


def _maybe_re_review(
    feature: Feature, phase: PhaseRecord, output: str, base: Path | None,
) -> Feature | None:
    """Post-FIXING/REVIEWING hook: schedule another review cycle if needed.

    Returns a refreshed Feature when a re-review/re-fix was scheduled,
    or ``None`` to indicate the loop should continue with the same feature.
    """
    if phase.name == PhaseName.FIXING:
        feature = _refresh_feature(feature.id, base) or feature
        if should_re_review(feature, base):
            setup_re_review(feature.id, base)
            return _refresh_feature(feature.id, base) or feature
        return None

    if (phase.name == PhaseName.REVIEWING
            and feature.metadata.review_cycles > 0
            and "APPROVE" not in output.upper()):
        feature = _refresh_feature(feature.id, base) or feature
        setup_re_fix(feature.id, base)
        return _refresh_feature(feature.id, base) or feature

    return None


# ── Post-phase dispatch ───────────────────────────────────────────


@dataclass
class _PostPhaseCtx:
    """Bundle of arguments shared by post-phase and on-failure handlers.

    Keeping this as one object lets the dispatcher signature stay
    narrow (just ``ctx -> bool | None``) so adding a new handler is one
    function + one entry in the dispatch table.
    """

    feature: Feature
    phase: PhaseRecord
    output: str
    metrics: PhaseMetrics
    elapsed: float
    model_label: str
    pre_phase_sha: str
    initial_untracked: list[str]
    totals: BuildTotals
    callbacks: BuildCallbacks
    base: Path | None
    base_branch: str


def _post_record_metrics(ctx: _PostPhaseCtx) -> None:
    """Default success handler: emit phase chip and add to totals."""
    ctx.callbacks.on_phase_success(ctx.phase.name, ctx.elapsed, ctx.metrics)
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed, model=ctx.model_label,
    )


def _post_commit_changes(ctx: _PostPhaseCtx) -> None:
    """Auto-commit + record commits/files-changed totals."""
    _handle_post_phase_commit(
        ctx.feature, ctx.phase, ctx.pre_phase_sha, True, ctx.output,
        ctx.metrics, ctx.elapsed, ctx.model_label, ctx.initial_untracked,
        ctx.totals, ctx.callbacks, ctx.base, ctx.base_branch,
    )


def _post_render_gate_panel(ctx: _PostPhaseCtx) -> None:
    """Show the gate panel and record metrics."""
    ctx.callbacks.on_gate_panel(ctx.feature.id, ctx.base)
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed, model=ctx.model_label,
    )


_POST_PHASE_HANDLERS: dict[str, Callable[[_PostPhaseCtx], None]] = {
    "commit_changes": _post_commit_changes,
    "render_gate_panel": _post_render_gate_panel,
}


def _dispatch_post_phase_success(
    feature: Feature,
    phase: PhaseRecord,
    pre_phase_sha: str,
    output: str,
    metrics: PhaseMetrics,
    elapsed: float,
    model_label: str,
    initial_untracked: list[str],
    totals: BuildTotals,
    callbacks: BuildCallbacks,
    base: Path | None,
    base_branch: str,
) -> None:
    """Route a successful phase to the handler named in its PhaseSpec.

    Reads ``PhaseSpec.post_phase`` and looks it up in the
    ``_POST_PHASE_HANDLERS`` dispatch table.  ``None`` (or an unknown
    key) falls back to the generic record-metrics handler.

    Adding a new phase no longer requires modifying the build loop —
    register a new handler under a new key, declare it in the spec.
    """
    ctx = _PostPhaseCtx(
        feature=feature, phase=phase, output=output, metrics=metrics,
        elapsed=elapsed, model_label=model_label,
        pre_phase_sha=pre_phase_sha, initial_untracked=initial_untracked,
        totals=totals, callbacks=callbacks, base=base, base_branch=base_branch,
    )
    handler = _POST_PHASE_HANDLERS.get(get_spec(phase.name).post_phase or "")
    if handler is None:
        _post_record_metrics(ctx)
        return
    handler(ctx)


# ── On-failure dispatch ───────────────────────────────────────────


def _on_failure_default(ctx: _PostPhaseCtx) -> bool:
    """Default failure handler: record metrics, no retry."""
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed,
        model=ctx.model_label, success=False,
    )
    return False


def _on_failure_gate_retry(ctx: _PostPhaseCtx) -> bool:
    """Gate-specific failure: try to schedule a retry; return True on success."""
    feature, should_retry = _handle_gate_result(
        ctx.feature, ctx.phase, ctx.output, ctx.metrics, ctx.elapsed,
        ctx.model_label, ctx.totals, ctx.callbacks, ctx.base,
    )
    ctx.feature = feature
    return should_retry


_ON_FAILURE_HANDLERS: dict[str, Callable[[_PostPhaseCtx], bool]] = {
    "gate_retry": _on_failure_gate_retry,
}


def _dispatch_on_failure(ctx: _PostPhaseCtx) -> tuple[Feature, bool]:
    """Route a failed phase to the handler named in its PhaseSpec.

    Returns ``(refreshed_feature, should_retry)``. Default behaviour is
    record-and-stop; only phases with an ``on_failure`` key get custom
    handling (currently: gate → retry loop).
    """
    handler = _ON_FAILURE_HANDLERS.get(get_spec(ctx.phase.name).on_failure or "")
    if handler is None:
        return ctx.feature, _on_failure_default(ctx)
    should_retry = handler(ctx)
    return ctx.feature, should_retry


# ── Execution loop ────────────────────────────────────────────────


def _run_execution_loop(
    feature: Feature,
    totals: BuildTotals,
    initial_untracked: list[str],
    stack: str | None,
    callbacks: BuildCallbacks,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    base_sha: str = "",
) -> tuple[Feature, bool]:
    """Run implementation, review, gate, and fixing phases."""
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

        # Capture HEAD up front so post-phase handlers (commit_changes,
        # …) can compute the diff window. Free for non-CODE phases — no
        # commits land between capture and end-of-phase, so the value
        # is harmless and the loop stays free of phase_type branching.
        pre_phase_sha = git.get_head_sha(short=False)

        start = time.monotonic()
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, base_sha=base_sha,
            stack=stack,
            phase_tool_listener=callbacks.phase_tool_listener,
        )
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)
            _dispatch_post_phase_success(
                feature, phase, pre_phase_sha, output, metrics,
                elapsed, model_label, initial_untracked, totals, callbacks,
                base, base_branch,
            )

            updated = _maybe_re_review(feature, phase, output, base)
            if updated is not None:
                feature = updated
                total = len(feature.phases)
                continue
        else:
            ctx = _PostPhaseCtx(
                feature=feature, phase=phase, output=output, metrics=metrics,
                elapsed=elapsed, model_label=model_label,
                pre_phase_sha=pre_phase_sha,
                initial_untracked=initial_untracked,
                totals=totals, callbacks=callbacks,
                base=base, base_branch=base_branch,
            )
            feature, should_retry = _dispatch_on_failure(ctx)
            if should_retry:
                continue

            fail_phase(feature.id, phase.name, output, base)
            callbacks.on_phase_failure(phase.name, elapsed, output)
            return feature, False

        feature = _refresh_feature(feature.id, base) or feature

    return feature, True


def _save_phase_commits_artifact(
    feature_id: str, phase_name: str,
    phase_result: PhaseResult,
    base: Path | None = None,
) -> None:
    """Persist commit summary as a JSON artifact for downstream phases."""
    data = {
        "commits": [
            {
                "sha": c.sha,
                "message": c.message,
                "files": c.files,
                "insertions": c.insertions,
                "deletions": c.deletions,
            }
            for c in phase_result.commits
        ],
        "total_files": len(phase_result.files_changed),
        "total_insertions": sum(c.insertions for c in phase_result.commits),
        "total_deletions": sum(c.deletions for c in phase_result.commits),
    }
    write_artifact(feature_id, f"{phase_name}.json", json.dumps(data, indent=2), base)


# ── Finalize ──────────────────────────────────────────────────────


def _maybe_warn_low_cache(callbacks: BuildCallbacks, base: Path | None) -> None:
    """Fire on_low_cache_warning when recent builds drop under the threshold."""
    recent = read_history(base, limit=_CACHE_WARNING_WINDOW)
    if len(recent) < _CACHE_WARNING_WINDOW:
        return
    avg_cache = sum(r.cache_hit_rate for r in recent) / _CACHE_WARNING_WINDOW
    if avg_cache < _LOW_CACHE_THRESHOLD:
        callbacks.on_low_cache_warning(avg_cache)


def _finalize_build(
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


# ── Main entry points ─────────────────────────────────────────────


def execute_build_loop(
    feature: Feature,
    feedback: str | None = None,
    base: Path | None = None,
    verbose: bool = False,
    base_branch: str = "main",
    worktree: bool = False,
    create_pr: bool = True,
    callbacks: BuildCallbacks | None = None,
) -> bool:
    """Run a feature through its phases end-to-end.

    When ``create_pr=True`` (default — ``devflow build``):
        1. Plan first (no branch yet) — show plan, ask confirmation
        2. **After confirmation**, create the git branch (or worktree)
        3. Run remaining phases with auto-commit
        4. Create PR on success

    Branch creation is deferred so that rejecting the plan never leaves
    an orphan branch behind (it stayed on the user's current branch
    while planning).

    When ``create_pr=False`` (``devflow do``):
        1. Stay on current branch (no branch creation)
        2. Run all phases identically (planning, confirmation, execution)
        3. No PR — on success, print the commit SHAs
        4. On failure, changes stay on branch (user decides)
    """
    cb = callbacks or BuildCallbacks()
    is_resuming = feedback is not None
    if worktree and base is None:
        base = main_repo_root()

    config = load_config(base)
    stack = config.stack
    totals = BuildTotals()
    branch = branch_name(feature.id) if create_pr else ""

    initial_sha = git.get_head_sha(short=False)

    # Capture untracked-file snapshot up front so the auto-commit step
    # later on can ignore files that already existed.  This is cheap and
    # safe regardless of branch creation timing.
    initial_untracked = git.get_untracked_files()

    if create_pr:
        cb.on_banner(feature, branch, stack)
    else:
        cb.on_do_banner(feature)

    # Resume bookkeeping (feedback, planning reset) must happen before
    # the planning loop runs — branch creation is *not* required yet.
    if is_resuming:
        _prepare_resume(feature.id, base, feedback)
        if feedback is not None:
            cb.on_resume_notice(feedback)

    feature, plan_output, ok = _run_planning_loop(feature, totals, stack, cb, base, verbose)
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        return False

    if plan_output and not cb.confirm_plan(plan_output, feature.id, create_pr):
        # Plan rejected — no branch was created, nothing to clean up.
        return False

    # Plan confirmed — now safe to create the branch.
    if create_pr:
        initial_untracked = _create_branch_or_worktree(feature, worktree)

    feature, ok = _run_execution_loop(
        feature, totals, initial_untracked, stack, cb, base, verbose,
        base_branch, base_sha=initial_sha,
    )
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        if not create_pr and initial_sha:
            current_sha = git.get_head_sha(short=False)
            if current_sha != initial_sha:
                cb.on_revert_hint(feature.id, initial_sha)
        return False

    if create_pr:
        return _finalize_build(feature, branch, totals, initial_untracked, cb, base, base_branch)

    feature = _refresh_feature(feature.id, base) or feature
    record = build_metrics_from(feature, totals, success=True)
    append_build_metrics(record, base)

    # Compare full SHAs — `git rev-parse --short` may emit more than 7
    # chars to disambiguate large repos, so the previous `[:7]` slice
    # could spuriously trigger on_do_success for an unchanged HEAD.
    current_sha = git.get_head_sha(short=False)
    cb.on_build_summary(feature, totals, None, "", None)
    if current_sha != initial_sha:
        cb.on_do_success(current_sha, initial_sha)
    return True


def _prepare_resume(
    feature_id: str, base: Path | None, feedback: str | None,
) -> None:
    """Reset planning phases and stash user feedback before re-planning."""
    reset_planning_phases(feature_id, base)
    with mutate_feature(feature_id, base) as tracked:
        if tracked:
            tracked.metadata.feedback = feedback


def _create_branch_or_worktree(feature: Feature, worktree: bool) -> list[str]:
    """Create branch (or worktree) after plan confirmation.

    Returns the untracked-file snapshot rooted at the working location.
    Safe to call when the branch already exists (e.g. resume) — git
    falls back to a switch.
    """
    if worktree:
        _branch, wt_path = git.create_worktree(feature.id)
        return git.get_untracked_files(cwd=wt_path)
    git.create_branch(feature.id)
    return git.get_untracked_files()
