"""PhaseSpinner — Rich Live spinner for phase execution.

Displays a single updating line showing the last tool action while a
Claude phase runs. Used by default (non-verbose) mode in runner.py.
"""

from __future__ import annotations

from types import TracebackType

from rich.live import Live
from rich.text import Text

from devflow.ui.console import console
from devflow.ui.formatting import tool_icon


class PhaseSpinner:
    """Rich Live spinner showing the last tool action in-place.

    Usage::

        with PhaseSpinner("implementing") as spinner:
            spinner.update("Read", "models.py")
            ...
    """

    def __init__(self, phase_name: str) -> None:
        self._phase_name = phase_name
        self._renderable = self._make_text("…")
        self._live = Live(
            self._renderable,
            console=console,
            refresh_per_second=8,
            transient=False,
        )

    def _make_text(self, action: str) -> Text:
        t = Text()
        t.append("⠋ ", style="cyan bold")
        t.append(self._phase_name, style="bold")
        t.append("  ·  ", style="dim")
        t.append(action, style="dim")
        return t

    def update(self, tool_name: str, summary: str) -> None:
        """Update the spinner text with the latest tool action."""
        icon = tool_icon(tool_name)
        action = f"{icon} {tool_name}  {summary}"
        self._renderable = self._make_text(action)
        self._live.update(self._renderable)

    def stop(self) -> None:
        """Stop the live display."""
        if self._live.is_started:
            self._live.stop()

    def __enter__(self) -> PhaseSpinner:
        self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
