"""Doctor: diagnostic checks for devflow installation health."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from devflow.integrations.gate import CheckResult, GateReport
from devflow.ui.console import console

# Alias for clarity — doctor uses the same report structure as gate.
DoctorReport = GateReport


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
    assets = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "agents"
    return _check_assets_synced("agents", assets, target)


def check_skills_synced(target: Path | None = None) -> CheckResult:
    """Check that skills are synced to ~/.claude/skills/."""
    target = target or (Path.home() / ".claude" / "skills")
    assets = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "skills"
    return _check_assets_synced("skills", assets, target)


def _check_assets_synced(name: str, assets_dir: Path, target_dir: Path) -> CheckResult:
    """Compare expected assets against installed ones."""
    if not assets_dir.is_dir():
        return CheckResult(name=name, passed=False, message=f"assets/{name}/ not found")

    expected = {f.name for f in assets_dir.glob("*.md")}
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
    """Check that .devflow/state.json exists and is valid."""
    from devflow.core.models import WorkflowState

    root = base or Path.cwd()
    state_file = root / ".devflow" / "state.json"

    if not state_file.exists():
        return CheckResult(
            name="init",
            passed=False,
            message=".devflow/state.json not found — run: devflow init",
        )

    try:
        raw = state_file.read_text()
        state = WorkflowState.model_validate_json(raw)
        n_features = len(state.features)
        stack_info = f", stack={state.stack}" if state.stack else ""
        return CheckResult(
            name="init",
            passed=True,
            message=f"{n_features} feature(s){stack_info}",
        )
    except Exception as exc:
        return CheckResult(
            name="init",
            passed=False,
            message=f"Invalid state.json: {exc}",
        )


def check_claude_default_model() -> CheckResult:
    """Check the default Claude Code model.

    devflow overrides per phase via ``--model``, so this only affects
    general interactive ``claude`` usage outside devflow. Warn when
    the global default is Opus (expensive).
    """
    from devflow.setup._settings import load_settings

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
    from devflow.setup._settings import load_settings
    from devflow.setup.install import HOOK_SCRIPT_NAME, HOOKS_DIR, SETTINGS_FILE

    hooks = hooks_dir or HOOKS_DIR
    cfg = settings_file or SETTINGS_FILE

    hook_path = hooks / HOOK_SCRIPT_NAME
    if not hook_path.exists():
        return CheckResult(
            name="hook",
            passed=False,
            message=f"{HOOK_SCRIPT_NAME} not found — run: devflow install",
        )

    data, err = load_settings(cfg)
    if err:
        return CheckResult(
            name="hook",
            passed=False,
            message=f"settings.json unreadable: {err}",
        )
    if not cfg.exists():
        return CheckResult(
            name="hook",
            passed=False,
            message="settings.json missing — run: devflow install",
        )

    hook_command = str(hook_path.resolve())
    post_compact = data.get("hooks", {}).get("PostCompact", [])
    registered = any(
        isinstance(entry, dict) and entry.get("command") == hook_command
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


def run_doctor(base: Path | None = None) -> DoctorReport:
    """Run all diagnostic checks and return the report."""
    report = DoctorReport()
    report.add(check_python_version())
    report.add(check_cli_available("claude", ["claude", "--version"]))
    report.add(check_cli_available("gh", ["gh", "--version"]))
    report.add(check_claude_default_model())
    report.add(check_agents_synced())
    report.add(check_skills_synced())
    report.add(check_hook_installed())
    report.add(check_devflow_init(base))
    return report


def render_doctor_report(report: DoctorReport) -> None:
    """Display the doctor diagnostic report using Rich."""
    lines = Text()
    for check in report.checks:
        icon = "\u2713" if check.passed else "\u2717"
        style = "green" if check.passed else "red"
        lines.append(f"  {icon} ", style=style)
        lines.append(f"{check.name}: ", style="bold")
        lines.append(f"{check.message}\n", style=style)
        if check.details:
            lines.append(f"    {check.details[:500]}\n", style="dim")

    verdict = "HEALTHY" if report.passed else "ISSUES FOUND"
    border = "green" if report.passed else "red"

    console.print(Panel(lines, title=f"Doctor — {verdict}", border_style=border))
