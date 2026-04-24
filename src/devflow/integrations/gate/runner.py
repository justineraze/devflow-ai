"""Gate orchestration: parallel check execution and phase integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from devflow.core.metrics import PhaseMetrics
from devflow.integrations.gate.checks import _checks_for_stack, _run_command_check
from devflow.integrations.gate.complexity import check_complexity
from devflow.integrations.gate.config import load_gate_config
from devflow.integrations.gate.context import GateContext, build_context
from devflow.integrations.gate.module_size import check_module_size
from devflow.integrations.gate.report import CheckResult, GateReport
from devflow.integrations.gate.secrets import scan_secrets

# Default timeouts for custom gate commands (seconds).
_CUSTOM_TIMEOUTS: dict[str, int] = {"lint": 60, "test": 120}


def _run_custom_check(name: str, shell_cmd: str, cwd: Path) -> CheckResult:
    """Run a custom shell command and return a CheckResult."""
    import subprocess

    from devflow.integrations.gate.report import CheckResult

    timeout = _CUSTOM_TIMEOUTS.get(name, 60)
    try:
        result = subprocess.run(
            shell_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")

    output = result.stdout if result.stdout else result.stderr
    if result.returncode == 0:
        message, details = "No issues", ""
    else:
        message = f"{name} failed (exit {result.returncode})"
        details = output[:2000]

    return CheckResult(name=name, passed=result.returncode == 0, message=message, details=details)


def run_gate(
    ctx: GateContext,
    base: Path | None = None,
    stack: str | None = None,
) -> GateReport:
    """Run all quality gate checks in parallel and return the report.

    Args:
        ctx: Gate context (audit vs build scoping + excludes).
        base: Project root directory (defaults to cwd).
        stack: Tech stack name (e.g. "python", "typescript", "php").
    """
    cwd = base or Path.cwd()
    custom_config = load_gate_config(cwd)
    report = GateReport(custom=custom_config is not None)

    # Build the command check futures — source differs but pattern is the same.
    if custom_config is not None:
        submit_commands = lambda pool: [  # noqa: E731
            pool.submit(_run_custom_check, name, cmd, cwd)
            for name, cmd in custom_config.items()
        ]
        worker_count = len(custom_config)
    else:
        checks = _checks_for_stack(stack)
        submit_commands = lambda pool: [  # noqa: E731
            pool.submit(_run_command_check, c.name, c.cmd, cwd, c.timeout, c.parse_output)
            for c in checks
        ]
        worker_count = len(checks)

    with ThreadPoolExecutor(max_workers=worker_count + 3) as pool:
        cmd_futures = submit_commands(pool)
        secrets_future = pool.submit(scan_secrets, base, ctx)
        complexity_future = pool.submit(check_complexity, base, ctx=ctx)
        module_size_future = pool.submit(check_module_size, base, ctx=ctx)

        for fut in cmd_futures:
            report.add(fut.result())
        report.add(secrets_future.result())
        report.add(complexity_future.result())
        report.add(module_size_future.result())

    return report


def run_gate_phase(
    base: Path | None = None,
    stack: str | None = None,
    feature_id: str | None = None,
    base_sha: str = "",
) -> tuple[bool, str, PhaseMetrics]:
    """Run the gate phase locally during a build.

    Constructs a **build** context scoped to the diff since *base_sha*.
    When *feature_id* is provided, the structured report is persisted as
    ``.devflow/<feature_id>/gate.json``.

    Returns ``(passed, summary_text, metrics)``.
    """
    import json

    from devflow.core.artifacts import write_artifact

    ctx = build_context(mode="build", base_sha=base_sha, base=base)
    report = run_gate(ctx, base, stack=stack)

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
