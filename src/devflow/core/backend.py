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

        Default implementation returns ``None`` (not abstract) so existing
        backends that don't override it still satisfy the protocol.
        """
        return None

    def check_available(self) -> tuple[bool, str]:
        """Verify the backend CLI/API is reachable.

        Returns ``(ok, message)`` — *message* is the version string
        on success or an error description on failure.
        """
        ...


# ── Backend registry ────────────────────────────────────────────────

_current_backend: Backend | None = None


def get_backend() -> Backend:
    """Return the active backend, defaulting to Claude Code.

    The backend is created once and cached for the process lifetime.
    Call ``set_backend()`` before first use to override.
    """
    global _current_backend  # noqa: PLW0603
    if _current_backend is None:
        from devflow.integrations.claude.backend import ClaudeCodeBackend

        _current_backend = ClaudeCodeBackend()
    return _current_backend


def set_backend(backend: Backend) -> None:
    """Override the active backend (useful for tests and alternative providers)."""
    global _current_backend  # noqa: PLW0603
    _current_backend = backend
