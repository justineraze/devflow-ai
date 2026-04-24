"""Gate orchestration: parallel check execution and phase integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from devflow.core.metrics import PhaseMetrics
from devflow.integrations.gate.checks import _checks_for_stack, _run_command_check
from devflow.integrations.gate.complexity import check_complexity
from devflow.integrations.gate.config import load_gate_config
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


def run_gate(base: Path | None = None, stack: str | None = None) -> GateReport:
    """Run all quality gate checks in parallel and return the report.

    When a ``.devflow/gate.yaml`` config exists, its ``lint`` / ``test``
    commands replace the stack-detected ones. The secrets, complexity, and
    module-size checks always run regardless.

    Args:
        base: Project root directory (defaults to cwd).
        stack: Tech stack name (e.g. "python", "typescript", "php").
            Determines which lint/test tools to run. Defaults to "python".
    """
    cwd = base or Path.cwd()
    custom_config = load_gate_config(cwd)
    report = GateReport(custom=custom_config is not None)

    if custom_config is not None:
        # Custom gate: run user-defined shell commands.
        with ThreadPoolExecutor(max_workers=len(custom_config) + 3) as pool:
            command_futures = [
                (name, pool.submit(_run_custom_check, name, cmd, cwd))
                for name, cmd in custom_config.items()
            ]
            secrets_future = pool.submit(scan_secrets, base)
            complexity_future = pool.submit(check_complexity, base)
            module_size_future = pool.submit(check_module_size, base)

            for _name, fut in command_futures:
                report.add(fut.result())
            report.add(secrets_future.result())
            report.add(complexity_future.result())
            report.add(module_size_future.result())
    else:
        # Stack-detected gate: use built-in check definitions.
        checks = _checks_for_stack(stack)
        with ThreadPoolExecutor(max_workers=len(checks) + 3) as pool:
            command_futures_stack = [
                pool.submit(
                    _run_command_check,
                    c.name, c.cmd, cwd, c.timeout, c.parse_output,
                )
                for c in checks
            ]
            secrets_future = pool.submit(scan_secrets, base)
            complexity_future = pool.submit(check_complexity, base)
            module_size_future = pool.submit(check_module_size, base)

            for fut in command_futures_stack:
                report.add(fut.result())
            report.add(secrets_future.result())
            report.add(complexity_future.result())
            report.add(module_size_future.result())

    return report


def run_gate_phase(
    base: Path | None = None,
    stack: str | None = None,
    feature_id: str | None = None,
) -> tuple[bool, str, PhaseMetrics]:
    """Run the gate phase locally (ruff + pytest + secrets).

    When *feature_id* is provided, the structured report is persisted as
    ``.devflow/<feature_id>/gate.json`` so a follow-up fixing phase can load
    the exact failures instead of parsing free-form text.

    Returns ``(passed, summary_text, metrics)`` — metrics is a blank
    PhaseMetrics since the gate is local and incurs no model cost.
    """
    import json

    from devflow.core.artifacts import write_artifact

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
