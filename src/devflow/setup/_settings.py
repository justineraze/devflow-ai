"""Atomic JSON settings helpers shared by install and doctor."""

from __future__ import annotations

import json
from pathlib import Path

from devflow.core.paths import atomic_write_text


def load_settings(path: Path) -> tuple[dict, str | None]:
    """Load JSON from *path*.

    Returns:
        (data, None)   — on success (empty dict when file is missing).
        ({}, error)    — on JSON decode error (error is a human-readable string).
    """
    if not path.exists():
        return {}, None

    try:
        data = json.loads(path.read_text())
        return data, None
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON in {path.name}: {exc}"


def write_settings_atomic(path: Path, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace).

    Creates parent directories if needed.
    """
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
