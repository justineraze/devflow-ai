"""Stack detection — scan project files and return the primary language."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from devflow.core.config import load_config

# Extensions mapped to language identifiers.
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".php": "php",
}

# Directories to skip during scanning.
_IGNORED_DIRS: set[str] = {".git", "node_modules", "__pycache__", ".venv", ".tox", ".mypy_cache"}


def detect_stack(path: Path) -> str | None:
    """Detect the primary language of a project by counting source files.

    Args:
        path: Root directory of the project to scan.

    Returns:
        The language with the most matching files (e.g. ``"python"``),
        or ``None`` if no recognized source files are found.
    """
    counts: Counter[str] = Counter()

    for item in walk_files(path):
        lang = _EXTENSION_MAP.get(item.suffix)
        if lang:
            counts[lang] += 1

    if not counts:
        return None

    return counts.most_common(1)[0][0]


def resolve_stack(base: Path | None = None) -> str | None:
    """Get the project stack: from saved state, falling back to detection.

    Reads `.devflow/state.json` first (set by `devflow init`). If absent,
    runs `detect_stack()` on the current directory. Returns None when
    nothing can be determined.
    """
    root = base or Path.cwd()
    saved = load_config(base).stack
    if saved:
        return saved
    return detect_stack(root)


def walk_files(root: Path) -> list[Path]:
    """Recursively list files, skipping ignored directories."""
    files: list[Path] = []
    try:
        for entry in root.iterdir():
            if entry.is_dir():
                if entry.name in _IGNORED_DIRS:
                    continue
                files.extend(walk_files(entry))
            elif entry.is_file():
                files.append(entry)
    except PermissionError:
        pass
    return files
