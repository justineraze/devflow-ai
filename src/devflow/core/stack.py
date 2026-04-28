"""StackPlugin protocol — abstraction for technology stack detection.

Each supported stack (Python, TypeScript, PHP, frontend) implements
this protocol.  ``detect_stack()`` iterates registered plugins and
returns the first match.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StackPlugin(Protocol):
    """Protocol for technology stack detection and configuration."""

    @property
    def name(self) -> str:
        """Stack identifier used in config and routing (e.g. 'python')."""
        ...

    def detect(self, project_root: Path) -> bool:
        """Return True if this stack matches the project at *project_root*."""
        ...

    def agent_name(self) -> str:
        """Return the specialized developer agent name (e.g. 'developer-python')."""
        ...

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        """Return gate check definitions as ``[(name, command_args), ...]``.

        Each entry is a check name and its command arguments list.
        Timeouts and output parsers are handled by the gate layer.
        """
        ...
