"""Runner — prompt building and Claude Code execution."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

from devflow.core.artifacts import context_deps_for, load_phase_output
from devflow.core.metrics import PhaseMetrics
from devflow.core.models import Feature, PhaseRecord, PhaseStatus
from devflow.orchestration.model_routing import (
    resolve_model,
)
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

# Skills injected per phase, on top of ALWAYS_ON_SKILLS.
PHASE_SKILLS: dict[str, tuple[str, ...]] = {
    "architecture": ("planning-rigor",),
    "planning":     ("planning-rigor",),
    "plan_review":  ("code-review", "planning-rigor"),
    "implementing": ("incremental-build", "tdd-discipline"),
    "fixing":       ("incremental-build", "tdd-discipline"),
    "reviewing":    ("code-review", "refactor-first"),
}

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
    skill_names = list(ALWAYS_ON_SKILLS) + list(PHASE_SKILLS.get(phase_name, ()))
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

    phase_by_name = {p.name: p for p in feature.phases}
    parts: list[str] = []
    for dep_name in deps:
        content = load_phase_output(feature.id, dep_name)
        if content is None:
            prev = phase_by_name.get(dep_name)
            if prev and prev.status == PhaseStatus.DONE and prev.output:
                content = prev.output
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

    feedback = feature.metadata.get("feedback")
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
    """Return specific instructions depending on the phase type."""
    instructions: dict[str, str] = {
        "architecture": (
            "## Instructions\n\n"
            "Analyze the feature scope and produce architectural decisions.\n"
            "Output your analysis in the format specified in your agent instructions.\n"
            "Focus on module boundaries, dependency impact, and data flow."
        ),
        "planning": (
            "## Instructions\n\n"
            "Create a step-by-step implementation plan for this feature.\n"
            "Output your plan in the structured format from your agent instructions.\n"
            "Each step must name the exact file and what to change."
        ),
        "plan_review": (
            "## Instructions\n\n"
            "Review the plan from the planning phase.\n"
            "Check for completeness, risks, and missing test coverage.\n"
            "Output APPROVE or REQUEST_CHANGES with specific feedback."
        ),
        "implementing": (
            "## Instructions\n\n"
            "Implement the plan step by step.\n"
            "Follow the plan exactly — one step at a time.\n"
            "Write tests alongside the code.\n"
            "Run ruff and pytest after each change.\n\n"
            "**IMPORTANT — Commits atomiques obligatoires:**\n"
            "After completing each plan step, you MUST run:\n"
            "  git add -A && git commit -m 'feat: <short description of step>'\n"
            "Do NOT batch multiple steps into a single commit.\n"
            "Each commit = one plan step, verified green (ruff + pytest pass)."
        ),
        "reviewing": (
            "## Instructions\n\n"
            "Review the implementation changes.\n"
            "Run: git diff to see all changes made during implementation.\n"
            "Check against the plan, look for bugs, security issues, and "
            "convention violations.\n"
            "Output your review in the structured format from your agent "
            "instructions."
        ),
        "fixing": (
            "## Instructions\n\n"
            "Address the review feedback from the reviewing phase.\n"
            "Fix each issue flagged as critical or warning.\n"
            "Run tests after each fix.\n\n"
            "**Commit each fix separately:**\n"
            "  git add -A && git commit -m 'fix: <short description>'\n"
            "Do NOT batch multiple fixes into one commit."
        ),
    }
    return instructions.get(phase_name, "")


def execute_phase(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
) -> tuple[bool, str, PhaseMetrics]:
    """Execute a phase by calling Claude Code.

    Streams tool invocations to the console as they happen. The final
    phase-summary chip is rendered by the caller from the returned
    PhaseMetrics — keeps the runner focused on I/O.
    """
    from devflow.orchestration.stream import format_tool_line, parse_event

    system_prompt = build_system_prompt(phase.name, agent_name)
    user_prompt = build_user_prompt(feature, phase)
    model = resolve_model(feature, phase)
    cwd = str(Path.cwd())

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
        )

        proc.stdin.write(user_prompt)
        proc.stdin.close()

        metrics = PhaseMetrics()
        tool_count = 0

        for line in proc.stdout:
            parsed = parse_event(line)
            if not parsed:
                continue
            kind, payload = parsed
            if kind == "tool":
                tool_count += 1
                console.print(f"[dim]{format_tool_line(payload)}[/dim]")
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


def run_gate_phase(
    base: Path | None = None,
    stack: str | None = None,
    feature_id: str | None = None,
) -> tuple[bool, str, PhaseMetrics]:
    """Run the gate phase locally (ruff + pytest + secrets).

    When *feature_id* is provided, the structured report is persisted
    as ``.devflow/<feature_id>/gate.json`` so a follow-up fixing phase
    can load the exact failures instead of parsing free-form text.
    Returns ``(passed, summary_text, metrics)`` — metrics is a blank
    PhaseMetrics since the gate is local and incurs no model cost.
    """
    import json

    from devflow.core.artifacts import write_artifact
    from devflow.core.metrics import PhaseMetrics
    from devflow.integrations.gate import run_gate

    report = run_gate(base, stack=stack)

    if feature_id:
        write_artifact(
            feature_id, "gate.json", json.dumps(report.to_dict(), indent=2), base,
        )

    lines = []
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        lines.append(f"{icon} {check.name}: {check.message}")
        if not check.passed and check.details:
            for detail in check.details.split("\n")[:10]:
                lines.append(f"    {detail}")

    return report.passed, "\n".join(lines), PhaseMetrics()
