"""Phase artifact builders — extract structured results from git state.

These helpers convert low-level git output (log, status, diff) into the
domain-level objects (``PhaseResult``, enriched diff summaries) that the
build loop consumes and persists as ``.devflow/<feature>/*.json``.

They live in ``orchestration/`` rather than ``integrations/git/`` because
they bridge git data and domain concerns (``CRITICAL_PATH_PATTERNS``,
``PhaseResult`` from ``core.metrics``) — they would otherwise create a
git→core coupling that should not exist in the integrations layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from devflow.core.artifacts import write_artifact
from devflow.core.metrics import CommitInfo, PhaseMetrics, PhaseResult
from devflow.core.security import CRITICAL_PATH_PATTERNS
from devflow.integrations.git.repo import (
    DiffSummary,
    get_branch_diff_summary,
    git_log_numstat,
    git_status_porcelain,
)


class EnrichedDiffSummary(TypedDict):
    """Branch diff summary enriched with critical-path detection."""

    lines_added: int
    lines_removed: int
    files_changed: int
    paths: list[str]
    critical_paths: list[str]


def collect_phase_result(
    pre_sha: str,
    success: bool,
    output: str,
    metrics: PhaseMetrics,
) -> PhaseResult:
    """Build a PhaseResult by comparing git state before and after a phase.

    Does at most 2 git calls (log + status). Gracefully returns an empty
    result if git is unavailable or the repo is in an unusual state.
    """
    commits: list[CommitInfo] = []
    all_files: set[str] = set()
    uncommitted = False

    log_output = git_log_numstat(pre_sha)
    if log_output:
        commits = _parse_log_numstat(log_output)
        for c in commits:
            all_files.update(c.files)

    status_output = git_status_porcelain()
    if status_output:
        uncommitted = True
        for line in status_output.splitlines():
            # Format: "XY path" or "XY path -> newpath"
            path = line[3:].split(" -> ")[-1].strip()
            if path:
                all_files.add(path)

    return PhaseResult(
        success=success,
        output=output,
        metrics=metrics,
        commits=commits,
        files_changed=sorted(all_files),
        uncommitted_changes=uncommitted,
    )


def _parse_log_numstat(raw: str) -> list[CommitInfo]:
    """Parse ``git log --format=%H%x00%s --numstat`` output into CommitInfo list."""
    commits: list[CommitInfo] = []
    current_sha = ""
    current_msg = ""
    current_files: list[str] = []
    current_ins = 0
    current_del = 0

    for line in raw.splitlines():
        if "\x00" in line:
            if current_sha:
                commits.append(CommitInfo(
                    sha=current_sha[:7],
                    message=current_msg,
                    files=current_files,
                    insertions=current_ins,
                    deletions=current_del,
                ))
            sha_msg = line.split("\x00", 1)
            current_sha = sha_msg[0]
            current_msg = sha_msg[1] if len(sha_msg) > 1 else ""
            current_files = []
            current_ins = 0
            current_del = 0
        elif line.strip():
            # numstat line: "added\tremoved\tpath"
            parts = line.split("\t")
            if len(parts) >= 3:
                if parts[0].isdigit():
                    current_ins += int(parts[0])
                if parts[1].isdigit():
                    current_del += int(parts[1])
                current_files.append(parts[2])

    if current_sha:
        commits.append(CommitInfo(
            sha=current_sha[:7],
            message=current_msg,
            files=current_files,
            insertions=current_ins,
            deletions=current_del,
        ))

    return commits


def persist_files_summary(
    feature_id: str,
    base: Path | None = None,
    base_branch: str = "main",
) -> None:
    """Write files.json capturing the branch-diff summary for downstream phases.

    Enriches the raw diff summary with ``critical_paths`` — paths matching
    security/auth/payment patterns defined in ``CRITICAL_PATH_PATTERNS``.
    """
    summary: DiffSummary = get_branch_diff_summary(base_branch)
    paths = summary.get("paths") or []
    critical = [
        p for p in paths
        if any(pat in p.lower() for pat in CRITICAL_PATH_PATTERNS)
    ]
    enriched: EnrichedDiffSummary = {
        "lines_added": summary["lines_added"],
        "lines_removed": summary["lines_removed"],
        "files_changed": summary["files_changed"],
        "paths": paths,
        "critical_paths": critical,
    }
    write_artifact(feature_id, "files.json", json.dumps(enriched, indent=2), base)
