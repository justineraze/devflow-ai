"""Post-phase dispatch — success and failure handlers for each phase type.

Extracted from build.py. The execution loop calls into this module
after each phase completes (or fails) to handle commits, gate retries,
review cycles, and metrics recording.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from devflow.core.artifacts import (
    read_artifact,
    save_phase_output,
    write_artifact,
)
from devflow.core.config import load_config
from devflow.core.metrics import BuildTotals, PhaseMetrics
from devflow.core.models import (
    Feature,
    PhaseName,
    PhaseRecord,
)
from devflow.core.phase_outputs import REFORMAT_FEEDBACK, parse_review_output
from devflow.core.phases import get_spec
from devflow.core.workflow import load_state, mutate_feature
from devflow.integrations import git
from devflow.integrations.git.repo import git_status_porcelain
from devflow.integrations.git.smart_messages import generate_commit_message
from devflow.orchestration.events import BuildCallbacks
from devflow.orchestration.phase_artifacts import (
    collect_phase_result,
    persist_files_summary,
)
from devflow.orchestration.phase_exec import (
    setup_gate_retry,
)
from devflow.orchestration.review import (
    setup_re_fix,
    setup_re_review,
    should_re_review,
)

_log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from devflow.core.metrics import PhaseResult


def _refresh_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Reload feature from state after a phase completes."""
    state = load_state(base)
    return state.get_feature(feature_id)


# ── Post-phase handlers ──────────────────────────────────────────


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
    """Auto-commit after implementing/fixing and record metrics."""
    if git_status_porcelain():
        msg = generate_commit_message(feature, phase=phase.name)
        _ = git.commit_changes(msg, exclude=initial_untracked)

    phase_result = collect_phase_result(pre_phase_sha, success, output, metrics)

    callbacks.on_phase_success(phase.name, elapsed, metrics)
    callbacks.on_phase_commits(phase.name, phase_result)
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
    from devflow.orchestration.retry import should_abort_retry

    totals.add(phase.name, metrics, elapsed, model=model_label, success=False)
    save_phase_output(feature.id, "gate", output, base)

    attempt = feature.metadata.gate_retry
    current_diff = git.get_diff() or ""
    if attempt > 0:
        prev_diff = read_artifact(feature.id, f"gate_diff_{attempt - 1}.txt", base) or ""
        config = load_config(base)
        if should_abort_retry(prev_diff, current_diff, config.gate.diff_min_threshold):
            _log.warning("Gate retry aborted — diff too similar to previous attempt")
            return feature, False
    write_artifact(feature.id, f"gate_diff_{attempt}.txt", current_diff, base)

    if setup_gate_retry(feature.id, base):
        callbacks.on_gate_panel(feature.id, base)
        callbacks.on_phase_auto_retry(phase.name, elapsed, "")
        feature = _refresh_feature(feature.id, base) or feature
        return feature, True
    return feature, False


def _needs_double_review(feature: Feature, base: Path | None) -> bool:
    """Return True if the feature touches paths requiring double review."""
    if feature.metadata.double_review_done:
        return False
    config = load_config(base)
    patterns = config.double_review_on
    if not patterns:
        return False

    files_json = read_artifact(feature.id, "files.json", base)
    if not files_json:
        return False
    try:
        data = json.loads(files_json)
        paths: list[str] = data.get("paths", [])
    except (json.JSONDecodeError, TypeError):
        return False

    return any(
        fnmatch(p, pat) for p in paths for pat in patterns
    )


def _schedule_reformat_retry(feature_id: str, base: Path | None) -> None:
    """Reset reviewing to PENDING for a reformat retry."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        reviewing = feature.find_phase(PhaseName.REVIEWING)
        if reviewing:
            reviewing.reset()
        feature.metadata.review_reformat_retries += 1


def _schedule_double_review(feature_id: str, base: Path | None) -> None:
    """Reset reviewing to PENDING for a second independent review."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        reviewing = feature.find_phase(PhaseName.REVIEWING)
        if reviewing:
            reviewing.reset()
        feature.metadata.double_review_done = True


def maybe_re_review(
    feature: Feature, phase: PhaseRecord, output: str, base: Path | None,
) -> Feature | None:
    """Post-FIXING/REVIEWING hook: schedule another review cycle if needed.

    Uses the structured review parser to determine the verdict instead of
    raw string matching. Handles reformat retry on UNKNOWN verdict and
    double-review on critical paths.

    Returns a refreshed Feature when a re-review/re-fix was scheduled,
    or ``None`` to indicate the loop should continue with the same feature.
    """
    if phase.name == PhaseName.FIXING:
        feature = _refresh_feature(feature.id, base) or feature
        if should_re_review(feature, base):
            setup_re_review(feature.id, base)
            return _refresh_feature(feature.id, base) or feature
        return None

    if phase.name != PhaseName.REVIEWING:
        return None

    parsed = parse_review_output(output)

    if parsed.verdict == "UNKNOWN":
        if feature.metadata.review_reformat_retries < 1:
            _log.warning("Reviewer output non-conforme, scheduling reformat retry")
            save_phase_output(feature.id, "reviewing", output, base)
            _schedule_reformat_retry(feature.id, base)
            with mutate_feature(feature.id, base) as feat:
                if feat:
                    feat.metadata.feedback = REFORMAT_FEEDBACK
            return _refresh_feature(feature.id, base) or feature
        _log.warning("Reviewer output still non-conforme after retry, treating as REQUEST_CHANGES")
        parsed.verdict = "REQUEST_CHANGES"

    write_artifact(
        feature.id,
        "review.json",
        json.dumps({
            "verdict": parsed.verdict,
            "blocking_issues": [
                {
                    "file": i.file, "line": i.line,
                    "category": i.category, "description": i.description,
                }
                for i in parsed.blocking_issues
            ],
            "non_blocking_notes": parsed.non_blocking_notes,
        }, indent=2),
        base,
    )

    if parsed.verdict == "APPROVE":
        if _needs_double_review(feature, base):
            _log.info("Critical paths touched, scheduling double review")
            _schedule_double_review(feature.id, base)
            return _refresh_feature(feature.id, base) or feature
        return None

    if feature.metadata.review_cycles > 0 or parsed.verdict == "REQUEST_CHANGES":
        feature = _refresh_feature(feature.id, base) or feature
        setup_re_fix(feature.id, base)
        return _refresh_feature(feature.id, base) or feature

    return None


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


# ── Post-phase dispatch ──────────────────────────────────────────


@dataclass
class PostPhaseCtx:
    """Bundle of arguments shared by post-phase and on-failure handlers."""

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


def _post_record_metrics(ctx: PostPhaseCtx) -> None:
    """Default success handler: emit phase chip and add to totals."""
    ctx.callbacks.on_phase_success(ctx.phase.name, ctx.elapsed, ctx.metrics)
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed, model=ctx.model_label,
    )


def _post_commit_changes(ctx: PostPhaseCtx) -> None:
    """Auto-commit + record commits/files-changed totals."""
    _handle_post_phase_commit(
        ctx.feature, ctx.phase, ctx.pre_phase_sha, True, ctx.output,
        ctx.metrics, ctx.elapsed, ctx.model_label, ctx.initial_untracked,
        ctx.totals, ctx.callbacks, ctx.base, ctx.base_branch,
    )


def _post_render_gate_panel(ctx: PostPhaseCtx) -> None:
    """Show the gate panel and record metrics."""
    ctx.callbacks.on_gate_panel(ctx.feature.id, ctx.base)
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed, model=ctx.model_label,
    )
    from devflow.hooks import run_hook

    run_hook("post-gate", "passed", cwd=ctx.base or Path.cwd())


_POST_PHASE_HANDLERS: dict[str, Callable[[PostPhaseCtx], None]] = {
    "commit_changes": _post_commit_changes,
    "render_gate_panel": _post_render_gate_panel,
}


def dispatch_post_phase_success(
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
    """Route a successful phase to the handler named in its PhaseSpec."""
    ctx = PostPhaseCtx(
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


# ── On-failure dispatch ──────────────────────────────────────────


def _on_failure_default(ctx: PostPhaseCtx) -> bool:
    """Default failure handler: record metrics, no retry."""
    ctx.totals.add(
        ctx.phase.name, ctx.metrics, ctx.elapsed,
        model=ctx.model_label, success=False,
    )
    return False


def _on_failure_gate_retry(ctx: PostPhaseCtx) -> bool:
    """Gate-specific failure: try to schedule a retry; return True on success."""
    feature, should_retry = _handle_gate_result(
        ctx.feature, ctx.phase, ctx.output, ctx.metrics, ctx.elapsed,
        ctx.model_label, ctx.totals, ctx.callbacks, ctx.base,
    )
    ctx.feature = feature

    from devflow.hooks import run_hook

    run_hook("post-gate", "failed", cwd=ctx.base or Path.cwd())

    return should_retry


_ON_FAILURE_HANDLERS: dict[str, Callable[[PostPhaseCtx], bool]] = {
    "gate_retry": _on_failure_gate_retry,
}


def dispatch_on_failure(ctx: PostPhaseCtx) -> tuple[Feature, bool]:
    """Route a failed phase to the handler named in its PhaseSpec.

    Returns ``(refreshed_feature, should_retry)``.
    """
    handler = _ON_FAILURE_HANDLERS.get(get_spec(ctx.phase.name).on_failure or "")
    should_retry = _on_failure_default(ctx) if handler is None else handler(ctx)

    if not should_retry:
        from devflow.hooks import run_hook

        run_hook(
            "on-failure", ctx.phase.name, ctx.output[:200],
            cwd=ctx.base or Path.cwd(),
        )

    return ctx.feature, should_retry
