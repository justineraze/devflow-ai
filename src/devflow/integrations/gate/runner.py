"""Gate orchestration: parallel check execution and phase integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from devflow.integrations.gate.checks import _checks_for_stack, _run_command_check
from devflow.integrations.gate.report import GateReport
from devflow.integrations.gate.secrets import scan_secrets


def run_gate(base: Path | None = None, stack: str | None = None) -> GateReport:
    """Run all quality gate checks in parallel and return the report.

    All checks (lint, tests, secret scan) are independent subprocess or
    I/O-bound operations — running them concurrently cuts wall-time by
    roughly the slowest-minus-others factor on typical Python repos
    (ruff ~300ms, pytest several seconds).

    Args:
        base: Project root directory (defaults to cwd).
        stack: Tech stack name (e.g. "python", "typescript", "php").
            Determines which lint/test tools to run. Defaults to "python".
    """
    cwd = base or Path.cwd()
    checks = _checks_for_stack(stack)
    report = GateReport()

    with ThreadPoolExecutor(max_workers=len(checks) + 1) as pool:
        command_futures = [
            pool.submit(
                _run_command_check,
                c.name, c.cmd, cwd, c.timeout, c.parse_output,
            )
            for c in checks
        ]
        secrets_future = pool.submit(scan_secrets, base)

        # Preserve declared order for a stable report layout.
        for fut in command_futures:
            report.add(fut.result())
        report.add(secrets_future.result())

    return report


def run_gate_phase(
    base: Path | None = None,
    stack: str | None = None,
    feature_id: str | None = None,
) -> tuple[bool, str, object]:
    """Run the gate phase locally (ruff + pytest + secrets).

    When *feature_id* is provided, the structured report is persisted as
    ``.devflow/<feature_id>/gate.json`` so a follow-up fixing phase can load
    the exact failures instead of parsing free-form text.

    Returns ``(passed, summary_text, metrics)`` — metrics is a blank
    PhaseMetrics since the gate is local and incurs no model cost.
    """
    import json

    from devflow.core.artifacts import write_artifact
    from devflow.core.metrics import PhaseMetrics

    report = run_gate(base, stack=stack)

    if feature_id:
        write_artifact(
            feature_id, "gate.json", json.dumps(report.to_dict(), indent=2), base,
        )

    lines = []
    for check in report.checks:
        if check.skipped:
            icon = "⚠"
        elif check.passed:
            icon = "✓"
        else:
            icon = "✗"
        lines.append(f"{icon} {check.name}: {check.message}")
        if not check.passed and not check.skipped and check.details:
            for detail in check.details.split("\n")[:10]:
                lines.append(f"    {detail}")

    return report.passed, "\n".join(lines), PhaseMetrics()
