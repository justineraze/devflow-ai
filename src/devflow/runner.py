"""Runner — executes phases by calling Claude Code with the right agent context."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from devflow.models import Feature, PhaseRecord, PhaseStatus

console = Console()

# Where agents live after `devflow install`.
INSTALLED_AGENTS_DIR = Path.home() / ".claude" / "agents"
# Fallback: bundled agents in the package.
BUNDLED_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "agents"


def _find_agent_file(agent_name: str) -> Path | None:
    """Locate the agent .md file, preferring installed over bundled."""
    for base in (INSTALLED_AGENTS_DIR, BUNDLED_AGENTS_DIR):
        path = base / f"{agent_name}.md"
        if path.exists():
            return path
    return None


def _load_agent_prompt(agent_name: str) -> str:
    """Load the agent's .md file content as system instructions."""
    path = _find_agent_file(agent_name)
    if not path:
        return ""
    return path.read_text()


def _build_phase_context(feature: Feature, phase: PhaseRecord) -> str:
    """Build contextual information from previous phases.

    Each phase gets the output of completed phases as context,
    so the planner's output feeds into the developer, etc.
    """
    parts: list[str] = []
    for prev in feature.phases:
        if prev.name == phase.name:
            break
        if prev.status == PhaseStatus.DONE and prev.output:
            parts.append(f"## Output from phase: {prev.name}\n\n{prev.output}")
    return "\n\n---\n\n".join(parts)


def build_prompt(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
) -> str:
    """Construct the full prompt sent to Claude Code for a phase.

    Structure:
    1. Agent instructions (from .md file)
    2. Feature context (description, workflow, current state)
    3. Previous phase outputs (plan feeds into implementation, etc.)
    4. Phase-specific instructions
    """
    agent_instructions = _load_agent_prompt(agent_name)
    previous_context = _build_phase_context(feature, phase)

    sections = []

    if agent_instructions:
        sections.append(agent_instructions)

    sections.append(f"""## Current task

Feature: {feature.id}
Description: {feature.description}
Workflow: {feature.workflow}
Current phase: {phase.name}
Feature status: {feature.status.value}""")

    if previous_context:
        sections.append(f"## Context from previous phases\n\n{previous_context}")

    # Phase-specific instructions.
    phase_instructions = _get_phase_instructions(phase.name, feature)
    if phase_instructions:
        sections.append(phase_instructions)

    return "\n\n---\n\n".join(sections)


def _get_phase_instructions(phase_name: str, feature: Feature) -> str:
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
            "Run ruff and pytest after each change.\n"
            "Commit each step atomically."
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
            "Run tests after each fix."
        ),
    }
    return instructions.get(phase_name, "")


def execute_phase(
    feature: Feature,
    phase: PhaseRecord,
    agent_name: str,
    timeout: int = 600,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Execute a phase by calling Claude Code.

    Args:
        feature: The feature being built.
        phase: The current phase to execute.
        agent_name: Which agent to use.
        timeout: Max seconds for Claude Code execution.
        dry_run: If True, print the prompt instead of executing.

    Returns:
        Tuple of (success: bool, output: str).
    """
    prompt = build_prompt(feature, phase, agent_name)

    if dry_run:
        console.print("[yellow]DRY RUN — prompt that would be sent:[/yellow]")
        console.print(prompt[:3000])
        if len(prompt) > 3000:
            console.print(f"[dim]... ({len(prompt)} chars total)[/dim]")
        return True, "[dry run]"

    console.print(f"[cyan]Executing phase {phase.name!r} with agent {agent_name}...[/cyan]")

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path.cwd()),
        )

        output = result.stdout.strip()
        if result.returncode == 0:
            return True, output
        else:
            error = result.stderr.strip() or output or "Unknown error"
            return False, error

    except FileNotFoundError:
        return False, (
            "Claude Code CLI not found. "
            "Install it: https://docs.anthropic.com/en/docs/claude-code"
        )
    except subprocess.TimeoutExpired:
        return False, f"Phase {phase.name!r} timed out after {timeout}s"


def run_gate_phase(base: Path | None = None) -> tuple[bool, str]:
    """Run the gate phase by executing devflow check directly.

    The gate phase is special — it doesn't need Claude Code,
    it runs the automated quality checks.
    """
    from devflow.gate import run_gate

    report = run_gate(base)
    summary_parts = []
    for check in report.checks:
        icon = "PASS" if check.passed else "FAIL"
        summary_parts.append(f"{check.name}: {icon} — {check.message}")

    summary = "\n".join(summary_parts)
    return report.passed, summary
