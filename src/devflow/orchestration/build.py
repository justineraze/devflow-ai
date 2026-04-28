"""Build loop — executes a feature through its phases end-to-end.

Orchestrator only: wires planning, execution, and finalization.

Planning loop            → planning.py
Execution loop           → execution.py
Post-phase dispatch      → phase_handlers.py
Finalization (PR, cache) → finalize.py
Feature lifecycle        → lifecycle.py
Phase state machine      → phase_exec.py
Model selection          → model_routing.py
Gate execution           → integrations/gate/
Review cycle logic       → review.py
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.config import load_config
from devflow.core.history import append_build_metrics, build_metrics_from
from devflow.core.metrics import BuildTotals
from devflow.core.models import Feature
from devflow.core.workflow import load_state, mutate_feature
from devflow.integrations import git
from devflow.integrations.git import branch_name, main_repo_root
from devflow.orchestration.events import BuildCallbacks
from devflow.orchestration.execution import run_execution_loop
from devflow.orchestration.finalize import finalize_build
from devflow.orchestration.phase_exec import reset_planning_phases
from devflow.orchestration.planning import run_planning_loop


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


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
    initial_untracked = git.get_untracked_files()

    from devflow.hooks import run_hook

    if not run_hook("pre-build", cwd=base):
        from devflow.core.console import console

        console.print(
            "[yellow]✗ Pre-build hook failed — the hook returned a non-zero exit code"
            " — Fix: check .claude/hooks/ for errors or remove the hook[/yellow]"
        )
        return False

    if create_pr:
        cb.on_banner(feature, branch, stack)
    else:
        cb.on_do_banner(feature)

    if is_resuming:
        _prepare_resume(feature.id, base, feedback)
        if feedback is not None:
            cb.on_resume_notice(feedback)

    feature, plan_output, ok = run_planning_loop(feature, totals, stack, cb, base, verbose)
    if not ok:
        feature = _refresh_feature(feature.id, base) or feature
        append_build_metrics(build_metrics_from(feature, totals, success=False), base)
        return False

    if plan_output and not cb.confirm_plan(plan_output, feature.id, create_pr):
        return False

    wt_cwd: Path | None = None
    if create_pr:
        initial_untracked, wt_cwd = _create_branch_or_worktree(feature, worktree, base)

    feature, ok = run_execution_loop(
        feature, totals, initial_untracked, stack, cb, base, verbose,
        base_branch, base_sha=initial_sha, cwd=wt_cwd,
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
        result = finalize_build(feature, branch, totals, initial_untracked, cb, base, base_branch)
        if wt_cwd is not None:
            git.remove_worktree(feature.id)
            with mutate_feature(feature.id, base) as feat:
                if feat:
                    feat.metadata.worktree_path = None
        return result

    feature = _refresh_feature(feature.id, base) or feature
    record = build_metrics_from(feature, totals, success=True)
    append_build_metrics(record, base)

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


def _create_branch_or_worktree(
    feature: Feature, worktree: bool, base: Path | None = None,
) -> tuple[list[str], Path | None]:
    """Create branch (or worktree) after plan confirmation.

    Returns ``(untracked_files, worktree_path)``. *worktree_path* is
    ``None`` when running on the current branch.
    """
    if worktree:
        _branch, wt_path = git.create_worktree(feature.id)
        with mutate_feature(feature.id, base) as feat:
            if feat:
                feat.metadata.worktree_path = str(wt_path)
        return git.get_untracked_files(cwd=wt_path), wt_path
    git.create_branch(feature.id)
    return git.get_untracked_files(), None
