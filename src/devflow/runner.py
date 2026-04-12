"""Runner — prompt building and Claude Code execution."""

from __future__ import annotations

import contextlib
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
    """Load the agent's .md file content, stripping YAML frontmatter."""
    path = _find_agent_file(agent_name)
    if not path:
        return ""
    content = path.read_text()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")
    return content


def _build_phase_context(feature: Feature, phase: PhaseRecord) -> str:
    """Build contextual information from previous phases."""
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
    """Construct the full prompt sent to Claude Code for a phase."""
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

    # Feedback injection for plan revision.
    feedback = feature.metadata.get("feedback")
    if feedback and phase.name == "planning":
        sections.append(
            "## Feedback utilisateur sur le plan précédent\n\n"
            "L'utilisateur a refusé le plan précédent avec ce retour :\n\n"
            f"> {feedback}\n\n"
            "Produis un nouveau plan qui prend en compte ce feedback. "
            "Ne répète pas les parties du plan qui n'ont pas changé, "
            "concentre-toi sur les modifications demandées."
        )

    phase_instructions = _get_phase_instructions(phase.name)
    if phase_instructions:
        sections.append(phase_instructions)

    return "\n\n---\n\n".join(sections)


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
) -> tuple[bool, str]:
    """Execute a phase by calling Claude Code.

    Captures output silently. No timeout — waits for Claude Code to finish.
    """
    from devflow.stream import (
        PhaseMetrics,
        format_cost,
        format_tokens,
        format_tool_line,
        parse_event,
    )

    prompt = build_prompt(feature, phase, agent_name)

    try:
        proc = subprocess.Popen(
            [
                "claude", "-p", "-",
                "--permission-mode", "acceptEdits",
                "--output-format", "stream-json",
                "--verbose",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(Path.cwd()),
        )

        # Send prompt and close stdin.
        proc.stdin.write(prompt)
        proc.stdin.close()

        metrics = PhaseMetrics()
        tool_count = 0

        # Stream stdout line by line, showing tool uses live.
        for line in proc.stdout:
            parsed = parse_event(line)
            if not parsed:
                continue
            kind, payload = parsed
            if kind == "tool":
                tool_count += 1
                console.print(f"  [dim]{format_tool_line(payload)}[/dim]")
            elif kind == "metrics":
                metrics = payload
                metrics.tool_count = tool_count

        proc.wait()

        # Display token + cost summary for the phase.
        if metrics.input_tokens or metrics.output_tokens:
            console.print(
                f"  [dim]→ {tool_count} tools | "
                f"{format_tokens(metrics.input_tokens)} in / "
                f"{format_tokens(metrics.output_tokens)} out | "
                f"{format_cost(metrics.cost_usd)}[/dim]"
            )

        if proc.returncode == 0:
            return True, metrics.final_text or "Phase completed"
        stderr = proc.stderr.read().strip()
        return False, stderr or metrics.final_text or "Unknown error"

    except FileNotFoundError:
        return False, (
            "Claude Code CLI not found. "
            "Install it: https://docs.anthropic.com/en/docs/claude-code"
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        with contextlib.suppress(Exception):
            proc.terminate()
        return False, "Interrupted by user"


def run_gate_phase(base: Path | None = None) -> tuple[bool, str]:
    """Run the gate phase locally (ruff + pytest + secrets)."""
    from devflow.gate import run_gate

    report = run_gate(base)
    lines = []
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        lines.append(f"{icon} {check.name}: {check.message}")
        if not check.passed and check.details:
            for detail in check.details.split("\n")[:10]:
                lines.append(f"    {detail}")

    return report.passed, "\n".join(lines)
