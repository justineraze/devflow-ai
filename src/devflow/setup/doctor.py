"""Doctor: diagnostic checks for devflow installation health."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from devflow.core.backend import get_backend
from devflow.core.config import load_config
from devflow.core.gate_report import CheckResult, GateReport
from devflow.core.models import WorkflowState
from devflow.core.paths import assets_dir
from devflow.setup._settings import load_settings
from devflow.setup.install import HOOK_SCRIPT_NAME, HOOKS_DIR, SETTINGS_FILE


def check_python_version() -> CheckResult:
    """Check that Python >= 3.11 is available."""
    major, minor = sys.version_info[:2]
    version = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) >= (3, 11):
        return CheckResult(name="python", passed=True, message=f"Python {version}")
    return CheckResult(
        name="python",
        passed=False,
        message=f"Python 3.11+ required, found {version}",
    )


def check_cli_available(name: str, cmd: list[str]) -> CheckResult:
    """Check that a CLI tool is available and runnable."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            first_line = (result.stdout.strip().split("\n")[0] if result.stdout.strip() else "OK")
            return CheckResult(name=name, passed=True, message=first_line)
        return CheckResult(
            name=name,
            passed=False,
            message=f"{name} returned exit code {result.returncode}",
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{name} not found — install it first",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, passed=False, message=f"{name} timed out")


def check_agents_synced(target: Path | None = None) -> CheckResult:
    """Check that agents are synced to ~/.claude/agents/."""
    target = target or (Path.home() / ".claude" / "agents")
    return _check_assets_synced("agents", assets_dir() / "agents", target)


def check_skills_synced(target: Path | None = None) -> CheckResult:
    """Check that skills are synced to ~/.claude/skills/."""
    target = target or (Path.home() / ".claude" / "skills")
    return _check_assets_synced("skills", assets_dir() / "skills", target)


def _check_assets_synced(name: str, source_dir: Path, target_dir: Path) -> CheckResult:
    """Compare expected assets against installed ones."""
    if not source_dir.is_dir():
        return CheckResult(name=name, passed=False, message=f"assets/{name}/ not found")

    expected = {f.name for f in source_dir.glob("*.md")}
    if not target_dir.is_dir():
        return CheckResult(
            name=name,
            passed=False,
            message=f"0/{len(expected)} synced — run: devflow install",
        )

    installed = {f.name for f in target_dir.glob("*.md")}
    missing = expected - installed
    synced = len(expected) - len(missing)

    if missing:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{synced}/{len(expected)} synced",
            details="Missing: " + ", ".join(sorted(missing)),
        )
    return CheckResult(name=name, passed=True, message=f"{synced}/{len(expected)} synced")


def check_devflow_init(base: Path | None = None) -> CheckResult:
    """Check that .devflow/ is initialized (config.yaml + state.json)."""
    root = base or Path.cwd()
    devflow_dir = root / ".devflow"
    config_file = devflow_dir / "config.yaml"
    state_file = devflow_dir / "state.json"

    missing = []
    if not config_file.exists():
        missing.append("config.yaml")
    if not state_file.exists():
        missing.append("state.json")

    if missing:
        files = " and ".join(missing)
        return CheckResult(
            name="init",
            passed=False,
            message=f".devflow/{files} not found — run: devflow install",
        )

    try:
        raw = state_file.read_text(encoding="utf-8")
        state = WorkflowState.model_validate_json(raw)
        n_features = len(state.features)
        config = load_config(base)
        stack_info = f", stack={config.stack}" if config.stack else ""
        return CheckResult(
            name="init",
            passed=True,
            message=f"{n_features} feature(s){stack_info}",
        )
    except (OSError, ValueError, KeyError) as exc:
        return CheckResult(
            name="init",
            passed=False,
            message=f"Invalid config/state: {exc}",
        )


def check_claude_default_model() -> CheckResult:
    """Check the default Claude Code model.

    devflow overrides per phase via ``--model``, so this only affects
    general interactive ``claude`` usage outside devflow. Warn when
    the global default is Opus (expensive).
    """
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return CheckResult(
            name="claude model",
            passed=True,
            message="no settings.json — uses Claude Code default",
        )

    data, err = load_settings(settings)
    if err:
        return CheckResult(
            name="claude model",
            passed=False,
            message=f"invalid settings.json: {err}",
        )

    model = data.get("model", "")
    if not model:
        return CheckResult(
            name="claude model",
            passed=True,
            message="no default set — Claude Code picks",
        )

    if "opus" in model.lower():
        return CheckResult(
            name="claude model",
            passed=False,
            message=(
                f"default is {model!r} (expensive)"
                " — set to 'sonnet' in ~/.claude/settings.json"
            ),
        )

    return CheckResult(
        name="claude model",
        passed=True,
        message=f"default: {model}",
    )


def check_hook_installed(
    settings_file: Path | None = None,
    hooks_dir: Path | None = None,
) -> CheckResult:
    """Check that the PostCompact hook is installed and registered.

    Fails if:
    - the hook script is missing from ``hooks_dir``, or
    - settings.json is missing / unreadable / lacks the PostCompact entry.
    """
    hooks = hooks_dir or HOOKS_DIR
    cfg = settings_file or SETTINGS_FILE

    hook_path = hooks / HOOK_SCRIPT_NAME
    if not hook_path.exists():
        return CheckResult(
            name="hook",
            passed=False,
            message=f"{HOOK_SCRIPT_NAME} not found — run: devflow install",
        )

    if not cfg.exists():
        return CheckResult(
            name="hook",
            passed=False,
            message="settings.json missing — run: devflow install",
        )
    data, err = load_settings(cfg)
    if err:
        return CheckResult(
            name="hook",
            passed=False,
            message=f"settings.json unreadable: {err}",
        )

    hook_command = str(hook_path.resolve())
    post_compact = data.get("hooks", {}).get("PostCompact", [])
    registered = any(
        isinstance(entry, dict)
        and any(h.get("command") == hook_command for h in entry.get("hooks", []))
        for entry in post_compact
    )
    if not registered:
        return CheckResult(
            name="hook",
            passed=False,
            message="PostCompact entry missing in settings.json — run: devflow install",
        )

    return CheckResult(
        name="hook",
        passed=True,
        message=f"PostCompact → {HOOK_SCRIPT_NAME}",
    )


_FIX_ACTIONS: dict[str, tuple[str, str | None]] = {
    # name -> (description, auto_command or None for manual)
    "agents": ("Run devflow install to sync agents", "auto"),
    "skills": ("Run devflow install to sync skills", "auto"),
    "hook": ("Run devflow install to register hook", "auto"),
    "init": ("Run devflow init to initialize project", "auto_init"),
    "gh": ("Install GitHub CLI", None),
    "python": ("Upgrade Python to 3.11+", None),
    "claude model": ("Edit ~/.claude/settings.json — set model to sonnet", None),
}

_MANUAL_FIX_HINTS: dict[str, str] = {
    "gh": "brew install gh  (macOS) or see https://cli.github.com/",
    "python": "brew install python@3.12 or pyenv install 3.12",
    "claude model": 'Edit ~/.claude/settings.json -> set "model" to "claude-sonnet-4-5-20250514"',
}


def run_doctor_fix(base: Path | None = None) -> GateReport:
    """Run doctor and propose fixes for failed checks."""
    from rich.prompt import Confirm

    from devflow.core.console import console

    report = run_doctor(base)

    failed = [c for c in report.checks if not c.passed]
    if not failed:
        console.print("[green]All checks passed — nothing to fix.[/green]")
        return report

    auto_fixes: list[str] = []
    manual_fixes: list[tuple[str, str]] = []

    for check in failed:
        fix_info = _FIX_ACTIONS.get(check.name)
        if fix_info:
            desc, action = fix_info
            if action in ("auto", "auto_init"):
                auto_fixes.append(check.name)
                console.print(f"[yellow]  ✗ {check.name}[/yellow]: {desc}")
            else:
                hint = _MANUAL_FIX_HINTS.get(check.name, desc)
                manual_fixes.append((check.name, hint))
                console.print(f"[yellow]  ✗ {check.name}[/yellow]: {hint} (manual)")
        else:
            # Backend-specific — check name might be "Claude Code" or "pi"
            console.print(f"[yellow]  ✗ {check.name}[/yellow]: {check.message}")

    if auto_fixes and Confirm.ask("\nApply automatic fixes?", default=True):  # type: ignore[arg-type]
        _apply_auto_fixes(auto_fixes, base)
        # Re-run doctor to verify
        console.print()
        report = run_doctor(base)

    if manual_fixes:
        console.print("\n[bold]Manual fixes needed:[/bold]")
        for name, hint in manual_fixes:
            console.print(f"  • {name}: {hint}")

    return report


def _apply_auto_fixes(fixes: list[str], base: Path | None = None) -> None:
    """Apply automatic fixes."""
    from devflow.core.console import console

    if any(name in ("agents", "skills", "hook") for name in fixes):
        from devflow.setup.install import install_all, render_install_report

        console.print("[dim]Running devflow install...[/dim]")
        result = install_all()
        render_install_report(result)

    if "init" in fixes:
        from devflow.core.config import load_config, save_config
        from devflow.core.workflow import ensure_devflow_dir, load_state, save_state

        root = base or Path.cwd()
        console.print("[dim]Initializing .devflow/...[/dim]")
        ensure_devflow_dir(root)
        config = load_config(root)
        save_config(config, root)
        state = load_state(root)
        save_state(state, root)
        console.print("[green]✓ Initialized .devflow/[/green]")


def run_doctor(base: Path | None = None) -> GateReport:
    """Run all diagnostic checks and return the report."""
    report = GateReport()

    report.add(check_python_version())

    backend = get_backend()
    ok, msg = backend.check_available()
    report.add(CheckResult(name=backend.name, passed=ok, message=msg))

    report.add(check_cli_available("gh", ["gh", "--version"]))
    report.add(check_claude_default_model())
    report.add(check_agents_synced())
    report.add(check_skills_synced())
    report.add(check_hook_installed())
    report.add(check_devflow_init(base))
    return report
