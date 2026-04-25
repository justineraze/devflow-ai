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
from devflow.orchestration.events import BuildCallbacks
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
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a single phase via the backend or local gate."""
    if get_spec(phase.name).phase_type == PhaseType.GATE:
        return run_gate_phase(
            base, stack=stack,
            feature_id=feature.id, base_sha=base_sha,
        )
    return runner.execute_phase(feature, phase, agent_name, verbose=verbose)


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
        git.commit_changes(msg, exclude=initial_untracked)

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


def _dispatch_post_phase_success(
    phase_type: PhaseType,
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
    """Route a successful phase to its type-specific post-handler.

    Replaces the inline ``if/elif spec.phase_type == ...`` in the
    execution loop, keeping the loop a pure orchestrator.
    """
    if phase_type is PhaseType.GATE:
        callbacks.on_gate_panel(feature.id, base)
        totals.add(phase.name, metrics, elapsed, model=model_label)
        return

    if phase_type is PhaseType.CODE:
        _handle_post_phase_commit(
            feature, phase, pre_phase_sha, True, output, metrics,
            elapsed, model_label, initial_untracked, totals, callbacks,
            base, base_branch,
        )
        return

    callbacks.on_phase_success(phase.name, elapsed, metrics)
    totals.add(phase.name, metrics, elapsed, model=model_label)


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

        spec = get_spec(phase.name)
        is_code_phase = spec.phase_type == PhaseType.CODE
        pre_phase_sha = git.get_head_sha(short=False) if is_code_phase else ""

        start = time.monotonic()
        success, output, metrics = _execute_phase(
            feature, phase, agent_name, base, verbose, base_sha=base_sha,
            stack=stack,
        )
        elapsed = time.monotonic() - start

        if success:
            complete_phase(feature.id, phase.name, output, base)
            _dispatch_post_phase_success(
                spec.phase_type, feature, phase, pre_phase_sha, output, metrics,
                elapsed, model_label, initial_untracked, totals, callbacks,
                base, base_branch,
            )

            updated = _maybe_re_review(feature, phase, output, base)
            if updated is not None:
                feature = updated
                total = len(feature.phases)
                continue
        else:
            if spec.phase_type == PhaseType.GATE:
                feature, should_retry = _handle_gate_result(
                    feature, phase, output, metrics, elapsed,
                    model_label, totals, callbacks, base,
                )
                if should_retry:
                    continue
            else:
                totals.add(phase.name, metrics, elapsed, model=model_label, success=False)

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
        1. Create git branch (or worktree)
        2. Run planning phases — show plan, ask confirmation
        3. Run remaining phases with auto-commit
        4. Create PR on success

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
    branch = ""

    initial_sha = git.get_head_sha(short=False)

    if create_pr:
        initial_untracked = _setup_branch(
            feature, base, worktree, is_resuming, feedback,
        )
        branch = branch_name(feature.id)
        cb.on_banner(feature, branch, stack)
    else:
        initial_untracked = git.get_untracked_files()
        cb.on_do_banner(feature)

    if is_resuming and feedback is not None:
        cb.on_resume_notice(feedback)

    feature, plan_output, ok = _run_planning_loop(feature, totals, stack, cb, base, verbose)
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        return False

    if plan_output and not cb.confirm_plan(plan_output, feature.id, create_pr):
        return False

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

    current_sha = git.get_head_sha()
    cb.on_build_summary(feature, totals, None, "", None)
    if current_sha != initial_sha[:7]:
        cb.on_do_success(current_sha, initial_sha)
    return True


def _setup_branch(
    feature: Feature,
    base: Path | None,
    worktree: bool,
    is_resuming: bool,
    feedback: str | None,
) -> list[str]:
    """Set up git branch or worktree, return initial untracked files."""
    if worktree:
        _branch, wt_path = git.create_worktree(feature.id)
        initial_untracked = git.get_untracked_files(cwd=wt_path)
        if is_resuming:
            reset_planning_phases(feature.id, base)
            with mutate_feature(feature.id, base) as tracked:
                if tracked:
                    tracked.metadata.feedback = feedback
        return initial_untracked

    initial_untracked = git.get_untracked_files()
    branch = branch_name(feature.id)
    if is_resuming:
        reset_planning_phases(feature.id, base)
        with mutate_feature(feature.id, base) as tracked:
            if tracked:
                tracked.metadata.feedback = feedback
        git.switch_branch(branch)
    else:
        git.create_branch(feature.id)

    return initial_untracked
