"""Runner — prompt building and Claude Code execution."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

from devflow.core.artifacts import context_deps_for, load_phase_output
from devflow.core.metrics import PhaseMetrics
from devflow.core.models import Feature, PhaseRecord
from devflow.core.phases import UnknownPhase, get_spec
from devflow.orchestration.model_routing import resolve_model
from devflow.ui.console import console

# Where agents and skills live after `devflow install`.
INSTALLED_AGENTS_DIR = Path.home() / ".claude" / "agents"
INSTALLED_SKILLS_DIR = Path.home() / ".claude" / "skills"
# Fallback: bundled assets in the package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BUNDLED_AGENTS_DIR = _PROJECT_ROOT / "assets" / "agents"
BUNDLED_SKILLS_DIR = _PROJECT_ROOT / "assets" / "skills"

# Skills always injected on every phase.
ALWAYS_ON_SKILLS: tuple[str, ...] = ("context-discipline",)

# Hard ceiling for a single Claude phase. 30 minutes covers planning
# and implementing on large features; anything past that is almost
# certainly a hung process and we'd rather kill it than freeze the CLI.
PHASE_TIMEOUT_S: int = 30 * 60


def _find_asset_file(name: str, installed_dir: Path, bundled_dir: Path) -> Path | None:
    """Locate an asset .md file, preferring installed over bundled."""
    for base in (installed_dir, bundled_dir):
        path = base / f"{name}.md"
        if path.exists():
            return path
    return None


def _find_agent_file(agent_name: str) -> Path | None:
    """Locate the agent .md file."""
    return _find_asset_file(agent_name, INSTALLED_AGENTS_DIR, BUNDLED_AGENTS_DIR)


def _find_skill_file(skill_name: str) -> Path | None:
    """Locate the skill .md file."""
    return _find_asset_file(skill_name, INSTALLED_SKILLS_DIR, BUNDLED_SKILLS_DIR)


def _load_md_content(path: Path | None) -> str:
    """Read an .md file and strip YAML frontmatter."""
    if not path:
        return ""
    content = path.read_text()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")
    return content


def _load_agent_prompt(agent_name: str) -> str:
    """Load the agent's .md file content."""
    return _load_md_content(_find_agent_file(agent_name))


def _load_skills_for_phase(phase_name: str) -> str:
    """Load and concatenate skill .md files relevant to a phase."""
    try:
        phase_skills = get_spec(phase_name).skills
    except UnknownPhase:
        phase_skills = ()
    skill_names = list(ALWAYS_ON_SKILLS) + list(phase_skills)
    sections = []
    for name in skill_names:
        content = _load_md_content(_find_skill_file(name))
        if content:
            sections.append(content)
    return "\n\n---\n\n".join(sections)


def _build_phase_context(feature: Feature, phase: PhaseRecord) -> str:
    """Build contextual information from previous phases.

    Instead of concatenating every previous phase's output (which bloats
    the user prompt and defeats prompt caching), only inject the phases
    this one actually depends on — see artifacts.PHASE_CONTEXT_DEPS.

    Falls back to in-memory phase.output when the on-disk artifact is
    missing (e.g. first run before the artifacts dir was introduced, or
    tests exercising the runner without a project dir).
    """
    deps = context_deps_for(phase.name)
    if not deps:
        return ""

    parts: list[str] = []
    for dep_name in deps:
        content = load_phase_output(feature.id, dep_name)
        if content:
            parts.append(f"## Output from phase: {dep_name}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def build_system_prompt(phase_name: str, agent_name: str) -> str:
    """Build the stable part of the prompt (skills + agent role).

    This content depends only on the phase type and agent, not on the
    specific feature. Passing it via `--system-prompt` lets Anthropic
    cache it across calls, reducing cost significantly.
    """
    sections = []

    skills = _load_skills_for_phase(phase_name)
    if skills:
        sections.append(f"# Skills (discipline rules)\n\n{skills}")

    agent_instructions = _load_agent_prompt(agent_name)
    if agent_instructions:
        sections.append(f"# Agent role\n\n{agent_instructions}")

    return "\n\n---\n\n".join(sections)


def build_user_prompt(feature: Feature, phase: PhaseRecord) -> str:
    """Build the variable part of the prompt (task + context + feedback).

    Changes on every call — not worth caching. Passed via stdin.
    """
    sections = []

    sections.append(f"""# Current task

Feature: {feature.id}
Description: {feature.description}
Workflow: {feature.workflow}
Current phase: {phase.name}
Feature status: {feature.status.value}""")

    previous_context = _build_phase_context(feature, phase)
    if previous_context:
        sections.append(f"# Context from previous phases\n\n{previous_context}")

    if phase.name == "fixing":
        from devflow.core.artifacts import read_artifact

        gate_json = read_artifact(feature.id, "gate.json")
        if gate_json:
            sections.append(
                "# Gate failures to fix (structured)\n\n"
                "The quality gate failed with the following checks. This is "
                "the authoritative source of truth — not the reviewer's "
                "free-form text. For each check with `passed: false`:\n"
                "- Read `details` for the exact errors (ruff rule codes, "
                "pytest test names with tracebacks, secret patterns).\n"
                "- Fix the failing check at its source, do not silence it.\n"
                "- After each fix, commit atomically "
                "(`git add -A && git commit -m 'fix: ...'`).\n"
                "- Re-run the failing tool locally to verify before moving on.\n\n"
                f"```json\n{gate_json}\n```"
            )

    feedback = feature.metadata.feedback
    if feedback and phase.name == "planning":
        sections.append(
            "# User feedback on previous plan\n\n"
            "The user rejected the previous plan with this feedback:\n\n"
            f"> {feedback}\n\n"
            "Produce a new plan that addresses this feedback. "
            "Don't repeat the unchanged parts; focus on the requested changes."
        )

    phase_instructions = _get_phase_instructions(phase.name)
    if phase_instructions:
        sections.append(phase_instructions)

    return "\n\n---\n\n".join(sections)


def build_prompt(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
) -> str:
    """Construct the full prompt as a single string.

    Backwards-compatible facade. For execution, prefer splitting into
    build_system_prompt() + build_user_prompt() so the stable part
    can be cached via --system-prompt.
    """
    system = build_system_prompt(phase.name, agent_name)
    user = build_user_prompt(feature, phase)
    parts = [p for p in (system, user) if p]
    return "\n\n---\n\n".join(parts)


def _get_phase_instructions(phase_name: str) -> str:
    """Return the instructions string for *phase_name*."""
    try:
        return get_spec(phase_name).instructions
    except UnknownPhase:
        return ""


def execute_phase(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
    verbose: bool = False,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a phase by calling Claude Code.

    In default mode, shows a Rich spinner updated with the last tool action.
    With ``verbose=True``, streams every tool line to the console instead
    (matches the original behaviour, useful for debugging).

    The final phase-summary chip is rendered by the caller from the returned
    PhaseMetrics — keeps the runner focused on I/O.
    """
    from devflow.orchestration.stream import format_tool_line, parse_event
    from devflow.ui.spinner import PhaseSpinner

    system_prompt = build_system_prompt(phase.name, agent_name)
    user_prompt = build_user_prompt(feature, phase)
    model = resolve_model(feature, phase)
    cwd = str(Path.cwd())

    # Prepend the active virtualenv's bin dir so the agent can run ruff,
    # pytest, devflow, etc. without PATH issues.
    venv_bin = str(Path(sys.executable).parent)
    agent_env = os.environ.copy()
    agent_env["PATH"] = f"{venv_bin}{os.pathsep}{agent_env.get('PATH', '')}"

    cmd = [
        "claude", "-p", "-",
        "--model", model,
        "--permission-mode", "acceptEdits",
        "--output-format", "stream-json",
        "--verbose",
    ]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=agent_env,
        )

        proc.stdin.write(user_prompt)
        proc.stdin.close()

        metrics = PhaseMetrics()
        tool_count = 0

        with PhaseSpinner(phase.name) as spinner:
            for line in proc.stdout:
                parsed = parse_event(line)
                if not parsed:
                    continue
                kind, payload = parsed
                if kind == "tool":
                    tool_count += 1
                    tool_line = format_tool_line(payload)
                    if verbose:
                        spinner.stop()
                        console.print(f"[dim]{tool_line}[/dim]")
                    else:
                        # Extract tool name + short summary for the spinner.
                        parts = tool_line.split(None, 2)
                        tool_name = parts[1] if len(parts) > 1 else "tool"
                        summary = parts[2] if len(parts) > 2 else ""
                        spinner.update(tool_name, summary)
                elif kind == "metrics":
                    metrics = payload
                    metrics.tool_count = tool_count

        try:
            proc.wait(timeout=PHASE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False, (
                f"Phase timed out after {PHASE_TIMEOUT_S}s. "
                "Increase PHASE_TIMEOUT_S or split the feature."
            ), metrics

        if proc.returncode == 0:
            return True, metrics.final_text or "Phase completed", metrics
        stderr = proc.stderr.read().strip()
        return False, stderr or metrics.final_text or "Unknown error", metrics

    except FileNotFoundError:
        return False, (
            "Claude Code CLI not found. "
            "Install it: https://docs.anthropic.com/en/docs/claude-code"
        ), PhaseMetrics()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        with contextlib.suppress(Exception):
            proc.terminate()
        return False, "Interrupted by user", PhaseMetrics()


