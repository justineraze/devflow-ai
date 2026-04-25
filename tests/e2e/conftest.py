"""Shared fixtures for e2e orchestration tests.

These tests verify the full build pipeline (state machine, git, artifacts,
gate) without calling claude -p.  The `mock_claude` fixture replaces
`execute_phase` with a canned response so the tests are fast, free, and
deterministic.  The gate phase is NOT mocked — ruff and pytest run for real
against the mini_python fixture.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from devflow.core.console import console
from devflow.core.metrics import PhaseMetrics

# Fixture project shipped with the tests.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mini_python"

# Canned phase outputs (stable, used by mock_claude).
_CANNED: dict[str, str] = {
    "architecture": (
        "## Architecture\n\n### Scope\n- Module: calculator\n\nNo structural changes needed."
    ),
    "planning": (
        "## Plan: feat-add-subtraction-0101 — Add subtract function to calculator\n\n"
        "### Scope\n- Type: extension\n- Module: calculator\n- Complexity: low\n\n"
        "### Affected files\n| File | Action | What changes |\n"
        "|------|--------|-------------|\n"
        "| src/calculator.py | modify | add subtract(a, b) |\n"
        "| tests/test_calculator.py | modify | add test_subtract |\n\n"
        "### Implementation steps\n"
        "1. **src/calculator.py** — add `subtract(a, b)` function.\n"
        "   Test: test_subtract verifies 5 - 3 == 2\n\n"
        "### Risks\n- None\n"
    ),
    "plan_review": "Plan looks good. No issues found.",
    "implementing": "Added subtract function and tests.",
    "reviewing": "Code quality is good. No issues found.",
    "fixing": "Fixed all gate issues.",
}


@pytest.fixture
def mini_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy the mini_python fixture to a fresh temp dir with a real git repo.

    Sets CWD to the project root so git.py's Path.cwd() calls work correctly.
    Initialises devflow state with stack=python.
    """
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_DIR, project)

    subprocess.run(["git", "init", "-b", "main"], cwd=project, capture_output=True)
    # Fallback for older git that doesn't support -b.
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@devflow.ai"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Devflow Test"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=project, capture_output=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial project"],
        cwd=project, capture_output=True,
    )

    monkeypatch.chdir(project)

    from devflow.core.config import DevflowConfig, save_config
    save_config(DevflowConfig(stack="python"), project)

    return project


@pytest.fixture
def mock_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace execute_phase (the claude -p bridge) with canned responses.

    The gate phase is handled separately by build.py (_execute_phase routes
    it to run_gate_phase directly), so this mock only affects planning,
    implementing, reviewing, fixing, etc.
    """
    def _fake(feature: object, phase: object, agent_name: str, verbose: bool = False) -> tuple:  # type: ignore[type-arg]
        output = _CANNED.get(phase.name, "Phase completed.")  # type: ignore[union-attr]
        return True, output, PhaseMetrics()

    monkeypatch.setattr("devflow.orchestration.runner.execute_phase", _fake)


@pytest.fixture
def no_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real GitHub API calls by stubbing push_and_create_pr."""
    monkeypatch.setattr(
        "devflow.integrations.git.push_and_create_pr",
        lambda feature, branch, exclude=None, base_branch="main": "https://github.com/test/repo/pull/1",
    )


@pytest.fixture
def callbacks_with_ui_confirm() -> object:
    """BuildCallbacks pre-wired with the real plan-confirmation renderer.

    Use this fixture in e2e tests that exercise the plan-confirmation flow
    (acceptance, rejection, resume).  Pass the result via
    ``execute_build_loop(..., callbacks=callbacks_with_ui_confirm)``.
    """
    from devflow.orchestration.events import BuildCallbacks
    from devflow.ui.rendering import render_plan_confirmation

    class _UIPrompter:
        def confirm_plan(self, plan: str, fid: str, pr: bool) -> bool:  # noqa: PLR6301
            return render_plan_confirmation(plan, fid, pr)

    return BuildCallbacks(prompter=_UIPrompter())


@pytest.fixture
def confirm_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-confirm the plan step (simulates user pressing Enter/y)."""
    monkeypatch.setattr(console, "input", lambda _: "y")
