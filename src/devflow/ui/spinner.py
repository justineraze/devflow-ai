"""PhaseSpinner — Rich Live spinner for phase execution.

Displays a single updating line showing the last tool action while a
Claude phase runs. Used by default (non-verbose) mode in runner.py.
"""

from __future__ import annotations

from types import TracebackType

from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from devflow.core.console import console
from devflow.core.formatting import tool_icon


class PhaseSpinner:
    """Rich Live spinner showing the last tool action in-place.

    Polling loop
    ------------
    Rich's ``Live`` widget runs an internal refresh loop at 8 fps — it
    re-renders the display grid on each tick without any external prompt.
    Callers drive the *content* of that display by calling :meth:`update`
    each time the backend emits a new tool event.  The two loops are
    intentionally decoupled: the render loop keeps the terminal alive and
    the spinner animating even if the agent is silent, while ``update``
    only changes what text is shown on the next tick.

    In practice ``update`` is wired to ``BuildCallbacks.phase_tool_listener``
    (see :mod:`devflow.cli`) so the spinner reflects the agent's most recent
    tool call throughout the phase, then stays visible after the phase
    completes (``transient=False``).

    Usage::

        with PhaseSpinner("implementing") as spinner:
            spinner.update("Read", "models.py")
            ...
    """

    def __init__(self, phase_name: str) -> None:
        self._phase_name = phase_name
        self._action = "waiting for agent…"
        self._spinner = Spinner("dots", style="cyan bold")
        self._live = Live(
            self._make_renderable(),
            console=console,
            refresh_per_second=8,
            transient=False,
        )

    def _make_renderable(self) -> Table:
        grid = Table.grid(padding=(0, 1))
        grid.add_row(
            self._spinner,
            f"[bold]{self._phase_name}[/bold]  [dim]·  {self._action}[/dim]",
        )
        return grid

    def update(self, tool_name: str, summary: str) -> None:
        """Update the spinner text with the latest tool action."""
        icon = tool_icon(tool_name)
        self._action = f"{icon} {tool_name}  {summary}"
        self._live.update(self._make_renderable())

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
