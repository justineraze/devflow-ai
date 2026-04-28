"""Interactive project initialization wizard — ``devflow init``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import structlog
from rich.prompt import Confirm, Prompt

from devflow.core.config import DevflowConfig, GateConfig, LinearConfig, save_config
from devflow.core.console import console
from devflow.core.workflow import ensure_devflow_dir, load_state, save_state

log = structlog.get_logger(__name__)

VALID_STACKS = ("python", "typescript", "php", "frontend", "auto-detect")
VALID_BACKENDS = ("claude", "pi")

# Default gate commands per stack.
_DEFAULT_GATE: dict[str, dict[str, str]] = {
    "python": {"lint": "ruff check .", "test": "python -m pytest -q --tb=short"},
    "typescript": {
        "lint": "npx biome check .",
        "test": "npx vitest run --reporter=verbose",
    },
    "frontend": {
        "lint": "npx biome check .",
        "test": "npx vitest run --reporter=verbose",
    },
    "php": {
        "lint": "./vendor/bin/pint --test",
        "test": "./vendor/bin/pest --compact",
    },
}


def run_init_wizard(
    *,
    stack: str | None = None,
    base_branch: str | None = None,
    backend: str | None = None,
    no_tracker: bool = False,
    linear_team: str | None = None,
    gate_lint: str | None = None,
    gate_test: str | None = None,
    base: Path | None = None,
    detect_stack_fn: Callable[[Path], str | None] | None = None,
    detect_base_branch_fn: Callable[[], str] | None = None,
) -> DevflowConfig:
    """Run the init wizard.  All params bypass interactive prompts when set.

    ``detect_stack_fn`` and ``detect_base_branch_fn`` are injected by the
    CLI layer so that the setup package never imports from integrations
    (respects the layering contract).
    """
    root = base or Path.cwd()
    interactive = _needs_interaction(
        stack, base_branch, backend, no_tracker, linear_team, gate_lint, gate_test,
    )

    _detect_stack = detect_stack_fn or _noop_detect_stack
    _detect_base = detect_base_branch_fn or _noop_detect_base_branch

    # 1. Stack -----------------------------------------------------------
    if stack is None:
        stack = (
            _prompt_stack(root, _detect_stack) if interactive
            else _detect_stack(root)
        )
    elif stack == "auto-detect":
        stack = _detect_stack(root)
        if interactive:
            console.print(
                f"[green]Auto-detected stack: {stack or 'unknown'}[/green]",
            )

    # 2. Base branch -----------------------------------------------------
    if base_branch is None:
        detected = _detect_base()
        if interactive:
            base_branch = Prompt.ask(
                "Branche cible pour les PRs ?",
                default=detected,
            )
        else:
            base_branch = detected

    # 3. Backend ---------------------------------------------------------
    if backend is None:
        if interactive:
            backend = Prompt.ask(
                "Quel backend IA ?",
                choices=list(VALID_BACKENDS),
                default="claude",
            )
        else:
            backend = "claude"

    if backend == "pi" and interactive:
        import shutil

        if not shutil.which("pi"):
            console.print(
                "[yellow]⚠ pi CLI not found"
                " — install it before using the pi backend.[/yellow]",
            )

    # 4. Tracker ---------------------------------------------------------
    tracker_team: str | None = linear_team
    if not no_tracker and linear_team is None and interactive:
        use_tracker = Prompt.ask(
            "Issue tracker ?",
            choices=["linear", "none"],
            default="none",
        )
        if use_tracker == "linear":
            tracker_team = Prompt.ask("Linear team ID")

    # 5. Gate commands ---------------------------------------------------
    if gate_lint is None and gate_test is None and interactive:
        custom_gate = Confirm.ask("Commandes gate custom ?", default=False)
        if custom_gate:
            gate_lint = Prompt.ask(
                "Lint command",
                default=_DEFAULT_GATE.get(stack or "", {}).get("lint", ""),
            )
            gate_test = Prompt.ask(
                "Test command",
                default=_DEFAULT_GATE.get(stack or "", {}).get("test", ""),
            )

    # Build config -------------------------------------------------------
    config = DevflowConfig(
        stack=stack,
        base_branch=base_branch or "main",
        backend=backend or "claude",
        gate=GateConfig(lint=gate_lint, test=gate_test),
        linear=LinearConfig(team=tracker_team),
    )

    # 6. Generate config.yaml -------------------------------------------
    ensure_devflow_dir(root)
    save_config(config, root)
    console.print("[green]✓ Generated .devflow/config.yaml[/green]")

    # 7. Update .gitignore -----------------------------------------------
    _update_gitignore(root)

    # 8. Ensure state.json -----------------------------------------------
    state = load_state(root)
    save_state(state, root)

    log.info("init_complete", stack=config.stack, backend=config.backend)
    return config


# ── Fallback detectors (when CLI doesn't inject real ones) ──────────


def _noop_detect_stack(_root: Path) -> str | None:
    return None


def _noop_detect_base_branch() -> str:
    return "main"


# ── Internal helpers ────────────────────────────────────────────────


def _needs_interaction(
    stack: str | None,
    base_branch: str | None,
    backend: str | None,
    no_tracker: bool,
    linear_team: str | None,
    gate_lint: str | None,
    gate_test: str | None,
) -> bool:
    """Return True if any choice needs interactive prompting."""
    tracker_resolved = no_tracker or linear_team is not None
    return not all([
        stack is not None,
        base_branch is not None,
        backend is not None,
        tracker_resolved,
        # gate is optional — resolved via auto-detect when not provided
    ])


def _prompt_stack(
    root: Path,
    detect_fn: Callable[[Path], str | None],
) -> str | None:
    """Prompt for stack selection with auto-detect option."""
    choice = Prompt.ask(
        "Quel est le stack principal ?",
        choices=list(VALID_STACKS),
        default="auto-detect",
    )
    if choice == "auto-detect":
        detected = detect_fn(root)
        console.print(f"[green]Auto-detected: {detected or 'unknown'}[/green]")
        return detected
    return choice


_GITIGNORE_ENTRIES = [
    ".devflow/state.json",
    ".devflow/.worktrees/",
    ".devflow/*.lock",
]


def _update_gitignore(root: Path) -> None:
    """Add devflow entries to .gitignore if absent."""
    gitignore = root / ".gitignore"
    existing = ""
    if gitignore.is_file():
        existing = gitignore.read_text(encoding="utf-8")

    lines_to_add = [e for e in _GITIGNORE_ENTRIES if e not in existing]
    if not lines_to_add:
        return

    with gitignore.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n# devflow\n")
        for line in lines_to_add:
            f.write(f"{line}\n")

    console.print("[green]✓ Updated .gitignore[/green]")
