"""PhaseSpinner — Rich Live spinner for phase execution.

Displays a single updating line showing the last tool action, elapsed
time, and tool count while a Claude phase runs.
"""
# tested on 2026-04-29

from __future__ import annotations

import time
from types import TracebackType

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from devflow.core.console import console
from devflow.core.formatting import tool_icon
from devflow.ui import theme


def _format_elapsed(seconds: float) -> str:
    """Format seconds as M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


class PhaseSpinner:
    """Rich Live spinner showing elapsed time, tool count, and last action.

    Implements Rich's renderable protocol so that ``Live`` calls
    ``__rich_console__`` on every refresh tick (8 fps), keeping the
    timer up to date even when the agent is silent.

    Usage::

        with PhaseSpinner("implementing") as spinner:
            spinner.update("Read", "models.py")
            ...
    """

    def __init__(self, phase_name: str) -> None:
        self._phase_name = phase_name
        self._action = "waiting for agent…"
        self._tool_count = 0
        self._start: float = 0.0
        self._spinner = Spinner("dots", style=f"{theme.ACCENT} bold")
        self._live = Live(
            self,
            console=console,
            refresh_per_second=8,
            transient=False,
        )

    def __rich_console__(
        self, console: Console, options: ConsoleOptions,
    ) -> RenderResult:
        elapsed = _format_elapsed(time.monotonic() - self._start) if self._start else "0:00"

        line = Text()
        line.append(f"{elapsed}  ", style=theme.TEXT_DIM)
        line.append(self._phase_name, style="bold")

        if self._tool_count:
            line.append(f" · {self._tool_count} tools", style=theme.TEXT_MUTED)

        line.append(f" · {self._action}", style=theme.TEXT_MUTED)

        grid = Table.grid(padding=(0, 1))
        grid.add_row(self._spinner, line)
        yield grid

    def update(self, tool_name: str, summary: str) -> None:
        """Update the spinner text with the latest tool action."""
        self._tool_count += 1
        icon = tool_icon(tool_name)
        self._action = f"{icon} {tool_name}  {summary}"

    def stop(self) -> None:
        """Stop the live display."""
        if self._live.is_started:
            self._live.stop()

    def __enter__(self) -> PhaseSpinner:
        self._start = time.monotonic()
        self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
