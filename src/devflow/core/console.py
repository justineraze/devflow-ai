"""Single shared Rich Console used across the codebase.

Keeping one instance avoids state conflicts between Live displays,
captures, and the various modules that need to print. Import as::

    from devflow.core.console import console
"""

from __future__ import annotations

from rich.console import Console

console: Console = Console()
