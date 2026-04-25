"""Stack detection — scan project files and return the primary language."""

from __future__ import annotations

import json
import os
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
_IGNORED_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", ".tox", ".mypy_cache"}
)

# Frontend framework markers found in package.json (dependencies or
# devDependencies). Any hit promotes a "typescript" project to "frontend".
_FRONTEND_PACKAGES: frozenset[str] = frozenset({
    "react", "react-dom", "next", "vue", "@vue/runtime-core",
    "svelte", "@sveltejs/kit", "solid-js", "preact", "@remix-run/react",
    "nuxt",
})


def detect_stack(path: Path) -> str | None:
    """Detect the primary language of a project.

    Returns the language with the most matching source files
    (e.g. ``"python"``), promoted to ``"frontend"`` when a JS/TS project
    declares a frontend framework dependency. Returns ``None`` when no
    recognized source files are found.
    """
    counts: Counter[str] = Counter()
    for item in _walk_files_iter(path):
        lang = _EXTENSION_MAP.get(item.suffix)
        if lang:
            counts[lang] += 1

    if not counts:
        return None

    primary = counts.most_common(1)[0][0]
    if primary == "typescript" and _has_frontend_framework(path):
        return "frontend"
    return primary


def resolve_stack(base: Path | None = None) -> str | None:
    """Return the project stack from saved config, falling back to detection."""
    root = base or Path.cwd()
    saved = load_config(base).stack
    if saved:
        return saved
    return detect_stack(root)


def walk_files(root: Path) -> list[Path]:
    """Recursively list files, skipping ignored directories.

    Public helper kept for callers that materialise the full list (e.g.
    file-count heuristics).  New code should prefer ``_walk_files_iter``.
    """
    return list(_walk_files_iter(root))


def _walk_files_iter(root: Path) -> list[Path]:
    """Walk *root* iteratively (``os.walk``) and return its files.

    Iterative to avoid recursion-depth blowouts on deep trees, and to
    prune ``_IGNORED_DIRS`` in place — recursion would visit them once
    before skipping their contents.
    """
    files: list[Path] = []
    if not root.is_dir():
        return files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        base = Path(dirpath)
        files.extend(base / name for name in filenames)
    return files


def _has_frontend_framework(path: Path) -> bool:
    """Return True if *path*/package.json declares a known frontend framework."""
    pkg = path / "package.json"
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    deps: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        section_data = data.get(section)
        if isinstance(section_data, dict):
            deps.update(section_data.keys())
    return bool(deps & _FRONTEND_PACKAGES)
