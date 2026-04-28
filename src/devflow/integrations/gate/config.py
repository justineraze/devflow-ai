"""Load optional per-project gate configuration.

Reads from the unified ``.devflow/config.yaml`` (``gate:`` section).
Falls back to the legacy ``.devflow/gate.yaml`` for migration
(the migration itself is handled by :func:`devflow.core.config.load_config`).
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.config import load_config


def load_gate_config(base: Path | None = None) -> dict[str, str] | None:
    """Load custom gate commands from the unified config.

    Returns a dict mapping check names (``"lint"``, ``"test"``) to shell
    commands, or *None* when no custom commands are configured — in which
    case the gate falls back to stack-based auto-detection.
    """

    config = load_config(base)
    gate = config.gate

    result: dict[str, str] = {}
    if gate.lint:
        result["lint"] = gate.lint
    if gate.test:
        result["test"] = gate.test

    return result or None
