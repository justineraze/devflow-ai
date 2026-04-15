"""Atomic JSON settings helpers shared by install and doctor."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path


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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        # Clean up the tmp file if anything goes wrong.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
