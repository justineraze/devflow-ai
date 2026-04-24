"""Gate orchestration: parallel check execution and phase integration."""

from __future__ import annotations

import json
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from devflow.core.gate_report import CheckResult, GateReport
from devflow.core.metrics import PhaseMetrics
from devflow.core.paths import venv_env
from devflow.integrations.gate.checks import checks_for_stack, run_command_check
from devflow.integrations.gate.complexity import check_complexity
from devflow.integrations.gate.config import load_gate_config
from devflow.integrations.gate.context import GateContext, build_context
from devflow.integrations.gate.module_size import check_module_size
from devflow.integrations.gate.secrets import scan_secrets

# Default timeouts for custom gate commands (seconds).
_CUSTOM_TIMEOUTS: dict[str, int] = {"lint": 60, "test": 120}


def _run_custom_check(name: str, shell_cmd: str, cwd: Path) -> CheckResult:
    """Run a custom shell command and return a CheckResult."""
    timeout = _CUSTOM_TIMEOUTS.get(name, 60)
    try:
        result = subprocess.run(
            shlex.split(shell_cmd),
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
            env=venv_env(cwd),
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


def _submit_custom_commands(
    pool: ThreadPoolExecutor,
    config: dict[str, str],
    cwd: Path,
) -> list[object]:
    """Submit custom gate checks to the thread pool."""
    return [
        pool.submit(_run_custom_check, name, cmd, cwd)
        for name, cmd in config.items()
    ]


def _submit_stack_commands(
    pool: ThreadPoolExecutor,
    stack: str | None,
    cwd: Path,
) -> list[object]:
    """Submit stack-specific gate checks to the thread pool."""
    checks = checks_for_stack(stack)
    return [
        pool.submit(run_command_check, c.name, c.cmd, cwd, c.timeout, c.parse_output)
        for c in checks
    ]


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

    with ThreadPoolExecutor(max_workers=8) as pool:
        if custom_config is not None:
            cmd_futures = _submit_custom_commands(pool, custom_config, cwd)
        else:
            cmd_futures = _submit_stack_commands(pool, stack, cwd)

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
