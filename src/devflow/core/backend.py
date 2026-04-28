"""Backend protocol — abstraction layer for AI code agents.

devflow delegates phase execution to a *backend*: a CLI tool or API
that runs prompts and returns structured output. The default backend
is Claude Code, but this protocol allows swapping it for any agent
that implements the same contract (OpenAI Codex, Aider, Ollama…).

Consumers never import a concrete backend directly — they receive one
via dependency injection (see ``get_backend()``).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from devflow.core.metrics import PhaseMetrics, ToolUse


class ModelTier(StrEnum):
    """Logical model tiers — mapped to concrete names by each backend.

    FAST     — cheap, fast, good for trivial fixes (lint, formatting).
    STANDARD — balanced cost/quality, default for most phases.
    THINKING — strongest reasoning, for architecture and planning.
    """

    FAST = "fast"
    STANDARD = "standard"
    THINKING = "thinking"


# Callback invoked for each tool event during streaming.
OnToolEvent = Callable[[ToolUse], None]


@runtime_checkable
class Backend(Protocol):
    """Protocol that every AI backend must implement."""

    @property
    def name(self) -> str:
        """Human-readable backend name (e.g. 'Claude Code')."""
        ...

    def model_name(self, tier: ModelTier) -> str:
        """Map a logical tier to the backend's concrete model name."""
        ...

    def execute(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        timeout: int,
        cwd: Path,
        env: dict[str, str],
        on_tool: OnToolEvent | None = None,
    ) -> tuple[bool, str, PhaseMetrics]:
        """Run a prompt and return ``(success, output, metrics)``.

        *model* is a concrete model name (from ``model_name()``).
        *on_tool* is called for each tool invocation during streaming,
        allowing the caller to update a spinner or log progress.
        """
        ...

    def one_shot(
        self,
        *,
        system: str,
        user: str,
        model: str,
        timeout: int,
    ) -> str | None:
        """Run a quick one-shot prompt and return the text result.

        Used for lightweight tasks (commit messages, titles, PR bodies)
        that don't need streaming or tool use.  Returns ``None`` on any
        failure — callers must provide a deterministic fallback.

        Backends must implement this — there is no default to discourage
        silent fallbacks where a backend pretends to support one-shot
        prompts but actually returns ``None`` for everything.
        """
        ...

    def check_available(self) -> tuple[bool, str]:
        """Verify the backend CLI/API is reachable.

        Returns ``(ok, message)`` — *message* is the version string
        on success or an error description on failure.
        """
        ...


# ── Backend registry (delegates to core.registry) ──────────────────

def get_backend() -> Backend:
    """Return the active backend.

    Delegates to :func:`devflow.core.registry.get_backend`.
    Raises ``RuntimeError`` if no backend has been registered.
    """
    from devflow.core.registry import get_backend as _reg_get

    return _reg_get()


def set_backend(backend: Backend) -> None:
    """Register *backend* as the active default.

    Delegates to :mod:`devflow.core.registry`.  The backend is
    registered under its ``name`` property (lowercased, spaces removed).
    """
    from devflow.core.registry import register_backend, set_active_backend

    key = backend.name.lower().replace(" ", "")
    register_backend(key, backend)
    set_active_backend(key)


def clear_backend() -> None:
    """Reset the registry — intended for test teardown."""
    from devflow.core.registry import clear_registry

    clear_registry()
