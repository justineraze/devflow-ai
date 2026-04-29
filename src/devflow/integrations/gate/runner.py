"""Gate orchestration: parallel check execution and phase integration."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from devflow.core.artifacts import write_artifact
from devflow.core.gate_report import MAX_CHECK_DETAILS_LEN, CheckResult, GateReport
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


def _timed(fn: Callable[..., CheckResult], *args: object, **kwargs: object) -> CheckResult:
    """Call *fn* and stamp the result with the elapsed wall-clock duration."""
    t0 = time.monotonic()
    result = fn(*args, **kwargs)
    result.duration_s = time.monotonic() - t0
    return result


def _run_custom_check(
    name: str, shell_cmd: str, cwd: Path, env: dict[str, str] | None = None,
) -> CheckResult:
    """Run a custom shell command and return a CheckResult.

    *env* may be supplied by the caller to share a venv-aware environment
    across parallel checks; otherwise it is computed lazily.
    """
    timeout = _CUSTOM_TIMEOUTS.get(name, 60)
    try:
        result = subprocess.run(
            shlex.split(shell_cmd),
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
            env=env if env is not None else venv_env(cwd),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")

    output = result.stdout if result.stdout else result.stderr
    if result.returncode == 0:
        message, details = "No issues", ""
    else:
        message = f"{name} failed (exit {result.returncode})"
        details = output[:MAX_CHECK_DETAILS_LEN]

    return CheckResult(name=name, passed=result.returncode == 0, message=message, details=details)


def _submit_custom_commands(
    pool: ThreadPoolExecutor,
    config: dict[str, str],
    cwd: Path,
    env: dict[str, str],
) -> list[Future[CheckResult]]:
    """Submit custom gate checks to the thread pool."""
    return [
        pool.submit(_timed, _run_custom_check, name, cmd, cwd, env)
        for name, cmd in config.items()
    ]


def _submit_stack_commands(
    pool: ThreadPoolExecutor,
    stack: str | None,
    cwd: Path,
    env: dict[str, str],
) -> list[Future[CheckResult]]:
    """Submit stack-specific gate checks to the thread pool."""
    checks = checks_for_stack(stack)
    return [
        pool.submit(_timed, run_command_check, c.name, c.cmd, cwd, c.timeout, c.parse_output, env)
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
    # Compute the venv-aware env once per build — every check shares the
    # same cwd, and ``os.environ.copy()`` per check adds up across the
    # 6+ parallel workers.
    env = venv_env(cwd)
    custom_config = load_gate_config(cwd)
    report = GateReport(custom=custom_config is not None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        if custom_config is not None:
            cmd_futures = _submit_custom_commands(pool, custom_config, cwd, env)
        else:
            cmd_futures = _submit_stack_commands(pool, stack, cwd, env)

        secrets_future = pool.submit(_timed, scan_secrets, base, ctx)
        complexity_future = pool.submit(_timed, check_complexity, base, ctx=ctx)
        module_size_future = pool.submit(_timed, check_module_size, base, ctx=ctx)

        all_futures: list[Future[CheckResult]] = [
            *cmd_futures, secrets_future, complexity_future, module_size_future,
        ]
        total = len(all_futures)

        from devflow.core.console import is_quiet

        if is_quiet():
            # Wait for all, then add in submission order.
            for fut in as_completed(all_futures):
                fut.result()  # ensure done, raise if failed
        else:
            from rich.progress import (
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
            )

            from devflow.core.console import console as gate_console

            gate_console.print()
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=gate_console,
                transient=True,
            ) as progress:
                ptask = progress.add_task("Running checks...", total=total)
                for fut in as_completed(all_futures):
                    check_result = fut.result()
                    progress.update(
                        ptask, advance=1,
                        description=f"Running checks... ({check_result.name})",
                    )

        # Add results in submission order for stable report ordering.
        for fut in all_futures:
            report.add(fut.result())

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
        lines.append(f"{icon} {check.name.ljust(12)} {check.message}")
        if not check.passed and not check.skipped and check.details:
            for detail in check.details.split("\n")[:10]:
                lines.append(f"    {detail}")

    return report.passed, "\n".join(lines), PhaseMetrics()
