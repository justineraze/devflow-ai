"""Re-export shim — the singleton now lives in core.

    from devflow.ui.console import console  # still works
"""

from devflow.core.console import console  # noqa: F401

__all__ = ["console"]
