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
    """Load the agent's .md file content, stripping YAML frontmatter."""
    path = _find_agent_file(agent_name)
    if not path:
        return ""
    content = path.read_text()
    # Strip YAML frontmatter (---\n...\n---) — it's metadata, not instructions.
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")
    return content


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

    # If resuming planning with feedback, inject it.
    feedback = feature.metadata.get("feedback")
    if feedback and phase.name == "planning":
        sections.append(
            "## Feedback utilisateur sur le plan précédent\n\n"
            f"L'utilisateur a refusé le plan précédent avec ce retour :\n\n"
            f"> {feedback}\n\n"
            "Produis un nouveau plan qui prend en compte ce feedback. "
            "Ne répète pas les parties du plan qui n'ont pas changé, "
            "concentre-toi sur les modifications demandées."
        )

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
) -> tuple[bool, str]:
    """Execute a phase by calling Claude Code.

    Captures output silently — the user sees only phase status.
    No timeout — waits for Claude Code to finish.

    Returns:
        Tuple of (success: bool, output: str).
    """
    prompt = build_prompt(feature, phase, agent_name)

    try:
        result = subprocess.run(
            [
                "claude", "-p", "-",
                "--permission-mode", "acceptEdits",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
        )

        output = result.stdout.strip()
        if result.returncode == 0:
            return True, output
        error = result.stderr.strip() or output or "Unknown error"
        return False, error

    except FileNotFoundError:
        return False, (
            "Claude Code CLI not found. "
            "Install it: https://docs.anthropic.com/en/docs/claude-code"
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return False, "Interrupted by user"


def run_gate_phase(base: Path | None = None) -> tuple[bool, str]:
    """Run the gate phase by executing devflow check directly."""
    from devflow.gate import run_gate

    report = run_gate(base)
    parts = []
    for check in report.checks:
        icon = "✓" if check.passed else "✗"
        parts.append(f"{icon} {check.name}: {check.message}")

    summary = "  ".join(parts)
    return report.passed, summary


def create_branch(feature_id: str) -> str:
    """Create and checkout a git branch for the feature.

    If the branch already exists, switches to it instead.
    Returns the actual branch name.
    """
    branch = f"feat/{feature_id}"
    cwd = str(Path.cwd())

    result = subprocess.run(
        ["git", "checkout", "-b", branch],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    # Branch already exists — switch to it.
    if result.returncode != 0:
        subprocess.run(
            ["git", "checkout", branch],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    return branch


def create_pull_request(
    feature: Feature,
    branch: str,
) -> str | None:
    """Create a GitHub PR for the feature.

    Returns the PR URL, or None if creation failed.
    """
    # Build PR body from phase outputs.
    body_parts = ["## Summary", "", feature.description, ""]

    for phase in feature.phases:
        if phase.status.value == "done" and phase.output and phase.output != "[dry run]":
            if phase.name == "planning":
                body_parts.extend(["## Plan", "", phase.output, ""])
            elif phase.name == "gate":
                body_parts.extend(["## Quality gate", "", phase.output, ""])

    body_parts.append("---")
    body_parts.append("Built with [devflow-ai](https://github.com/JustineRaze/devflow-ai)")

    body = "\n".join(body_parts)
    title = feature.description[:70]
    cwd = str(Path.cwd())

    # Commit any uncommitted changes (Claude Code may not have committed).
    # Stage everything first, then check if there's anything to commit.
    subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cwd,
        capture_output=True,
    )
    if diff.returncode != 0:  # There are staged changes.
        subprocess.run(
            ["git", "commit", "-m", f"feat: {feature.description}"],
            cwd=cwd,
            capture_output=True,
        )

    # Verify we have commits ahead of main before pushing.
    ahead = subprocess.run(
        ["git", "rev-list", "--count", "main..HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if ahead.stdout.strip() == "0":
        console.print("[yellow]No changes to push — branch is identical to main.[/yellow]")
        return None

    # Push branch then create PR.
    push = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
    )
    if push.returncode != 0:
        console.print(f"[red]Push failed: {push.stderr.strip()}[/red]")
        return None

    pr = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
    )
    if pr.returncode == 0:
        return pr.stdout.strip()

    console.print(f"[red]PR creation failed: {pr.stderr.strip()}[/red]")
    return None
