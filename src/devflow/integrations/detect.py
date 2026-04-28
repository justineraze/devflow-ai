"""Stack detection — StackPlugin implementations + detect_stack().

Each supported stack (python, typescript, php, frontend) is a
``StackPlugin`` implementation.  ``detect_stack()`` iterates registered
plugins and returns the first match.
"""

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

# Frontend framework markers found in package.json.
_FRONTEND_PACKAGES: frozenset[str] = frozenset({
    "react", "react-dom", "next", "vue", "@vue/runtime-core",
    "svelte", "@sveltejs/kit", "solid-js", "preact", "@remix-run/react",
    "nuxt",
})


# ── Shared helpers ───────────────────────────────────────────────────


def _walk_files_iter(root: Path) -> list[Path]:
    """Walk *root* iteratively and return its files, pruning ignored dirs."""
    files: list[Path] = []
    if not root.is_dir():
        return files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        base = Path(dirpath)
        files.extend(base / name for name in filenames)
    return files


def walk_files(root: Path) -> list[Path]:
    """Recursively list files, skipping ignored directories."""
    return list(_walk_files_iter(root))


def _count_languages(root: Path) -> Counter[str]:
    """Count source files per language in *root*."""
    counts: Counter[str] = Counter()
    for item in _walk_files_iter(root):
        lang = _EXTENSION_MAP.get(item.suffix)
        if lang:
            counts[lang] += 1
    return counts


def _primary_language(root: Path) -> str | None:
    """Return the language with the most source files, or None."""
    counts = _count_languages(root)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


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


# ── StackPlugin implementations ─────────────────────────────────────


class FrontendStack:
    """Frontend stack — TypeScript/JavaScript project with a framework."""

    @property
    def name(self) -> str:
        return "frontend"

    def detect(self, project_root: Path) -> bool:
        return (
            _primary_language(project_root) == "typescript"
            and _has_frontend_framework(project_root)
        )

    def agent_name(self) -> str:
        return "developer-frontend"

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        return [
            ("biome", ["npx", "biome", "check", "."]),
            ("vitest", ["npx", "vitest", "run", "--reporter=verbose"]),
        ]


class PythonStack:
    """Python stack."""

    @property
    def name(self) -> str:
        return "python"

    def detect(self, project_root: Path) -> bool:
        return _primary_language(project_root) == "python"

    def agent_name(self) -> str:
        return "developer-python"

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        return [
            ("ruff", ["ruff", "check", "."]),
            ("pytest", ["python", "-m", "pytest", "-q", "--tb=short"]),
        ]


class TypeScriptStack:
    """TypeScript/JavaScript stack (without frontend framework)."""

    @property
    def name(self) -> str:
        return "typescript"

    def detect(self, project_root: Path) -> bool:
        return (
            _primary_language(project_root) == "typescript"
            and not _has_frontend_framework(project_root)
        )

    def agent_name(self) -> str:
        return "developer-typescript"

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        return [
            ("biome", ["npx", "biome", "check", "."]),
            ("vitest", ["npx", "vitest", "run", "--reporter=verbose"]),
        ]


class PhpStack:
    """PHP stack."""

    @property
    def name(self) -> str:
        return "php"

    def detect(self, project_root: Path) -> bool:
        return _primary_language(project_root) == "php"

    def agent_name(self) -> str:
        return "developer-php"

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        return [
            ("pint", ["./vendor/bin/pint", "--test"]),
            ("pest", ["./vendor/bin/pest", "--compact"]),
        ]


# Ordered most-specific first: frontend before typescript.
STACK_PLUGINS: list[FrontendStack | PythonStack | TypeScriptStack | PhpStack] = [
    FrontendStack(),
    PythonStack(),
    TypeScriptStack(),
    PhpStack(),
]


# ── Public API ───────────────────────────────────────────────────────


def detect_stack(path: Path) -> str | None:
    """Detect the primary stack by iterating registered plugins.

    Returns the name of the first matching plugin, or ``None`` when no
    recognized source files are found.
    """
    for plugin in STACK_PLUGINS:
        if plugin.detect(path):
            return plugin.name
    return None


def get_stack_plugin(name: str) -> FrontendStack | PythonStack | TypeScriptStack | PhpStack | None:
    """Return the StackPlugin for *name*, or None."""
    for plugin in STACK_PLUGINS:
        if plugin.name == name:
            return plugin
    return None


def resolve_stack(base: Path | None = None) -> str | None:
    """Return the project stack from saved config, falling back to detection."""
    root = base or Path.cwd()
    saved = load_config(base).stack
    if saved:
        return saved
    return detect_stack(root)
