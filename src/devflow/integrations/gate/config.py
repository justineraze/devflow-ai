"""Load optional per-project gate configuration from .devflow/gate.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_VALID_KEYS = {"lint", "test"}


def load_gate_config(base: Path | None = None) -> dict[str, str] | None:
    """Load custom gate commands from ``.devflow/gate.yaml``.

    Returns a dict mapping check names (``"lint"``, ``"test"``) to shell
    commands, or *None* when the file is absent — in which case the gate
    falls back to stack-based auto-detection.

    Raises ``ValueError`` for invalid keys (anything outside ``lint`` / ``test``).
    """
    root = base or Path.cwd()
    config_path = root / ".devflow" / "gate.yaml"

    if not config_path.is_file():
        return None

    data: Any = yaml.safe_load(config_path.read_text())
    if not isinstance(data, dict) or not data:
        return None

    unknown = set(data.keys()) - _VALID_KEYS
    if unknown:
        msg = f"Unknown keys in gate.yaml: {', '.join(sorted(unknown))}"
        raise ValueError(msg)

    return {k: str(v) for k, v in data.items()}
