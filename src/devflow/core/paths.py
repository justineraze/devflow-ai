"""Common path and environment helpers.

These utilities were previously duplicated across ``setup/install.py``,
``setup/doctor.py``, ``core/workflow.py``, ``core/artifacts.py``,
``integrations/gate.py``, ``orchestration/runner.py`` and
``setup/_settings.py``. Centralising them here removes the drift risk
when the package layout changes (e.g. splitting a module) and fixes a
latent bug where the hard-coded ``parent.parent.parent.parent`` chain
pointed outside ``site-packages/`` under wheel installs.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

# This file lives at ``src/devflow/core/paths.py``. Its grand-parents:
#   parents[0] = core/
#   parents[1] = devflow/
#   parents[2] = src/ (editable install) or site-packages/ (wheel install)
#   parents[3] = repo root (editable) or parent of site-packages (wheel)
#
# Editable install: assets at parents[3] / "assets"
# Wheel install:   assets at parents[2] / "assets" (see pyproject.toml's
#                  ``[tool.hatch.build.targets.wheel.force-include]``).
_HERE = Path(__file__).resolve()
_CANDIDATE_DEPTHS: tuple[int, ...] = (3, 2)


def _resolve_sibling(name: str) -> Path:
    """Return ``<root>/<name>`` for the first existing candidate, else editable fallback."""
    for depth in _CANDIDATE_DEPTHS:
        candidate = _HERE.parents[depth] / name
        if candidate.is_dir():
            return candidate
    return _HERE.parents[_CANDIDATE_DEPTHS[0]] / name


def project_root() -> Path:
    """Return the project root, tolerant of editable and wheel installs.

    Identifies the root by looking for ``assets/`` or ``pyproject.toml``;
    falls back to the editable layout (``parents[3]``) when neither is
    found — which keeps tests running even on layouts that predate a
    full wheel build.
    """
    for depth in _CANDIDATE_DEPTHS:
        candidate = _HERE.parents[depth]
        if (candidate / "assets").is_dir() or (candidate / "pyproject.toml").exists():
            return candidate
    return _HERE.parents[_CANDIDATE_DEPTHS[0]]


def assets_dir() -> Path:
    """Return the bundled ``assets/`` directory (agents + skills)."""
    return _resolve_sibling("assets")


def workflows_dir() -> Path:
    """Return the bundled ``workflows/`` directory."""
    return _resolve_sibling("workflows")


def venv_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with the active venv's bin dir on PATH.

    Ensures tools installed in the current virtualenv (ruff, pytest, devflow…)
    are discoverable even when devflow was invoked from outside an activated
    shell — previously duplicated in ``gate.py`` and ``runner.py``.
    """
    venv_bin = str(Path(sys.executable).parent)
    env = os.environ.copy()
    env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via ``tempfile`` + ``os.replace``.

    Creates parent directories if missing. On failure, the temporary file
    is cleaned up and the exception propagates. The rename is atomic on
    POSIX when source and destination live on the same filesystem (we
    ensure that by placing the temp file in ``path.parent``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}-", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
