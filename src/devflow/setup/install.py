"""Install and sync agents/skills to ~/.claude/ directories."""

from __future__ import annotations

import shutil
from pathlib import Path

from devflow.ui.console import console

# Package assets directory (relative to this file).
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "assets"

# Default Claude Code directories.
CLAUDE_DIR = Path.home() / ".claude"
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"


def _sync_directory(
    source: Path,
    target: Path,
    label: str,
) -> list[str]:
    """Copy .md files from source to target, returning list of synced filenames."""
    if not source.exists():
        console.print(f"[yellow]Warning: {label} source not found: {source}[/yellow]")
        return []

    target.mkdir(parents=True, exist_ok=True)
    synced: list[str] = []

    for md_file in sorted(source.glob("*.md")):
        dest = target / md_file.name
        shutil.copy2(md_file, dest)
        synced.append(md_file.name)

    return synced


def install_agents(
    source: Path | None = None,
    target: Path | None = None,
) -> list[str]:
    """Install agent definitions to ~/.claude/agents/.

    Returns list of installed agent filenames.
    """
    src = (source or ASSETS_DIR) / "agents"
    dst = target or AGENTS_DIR
    return _sync_directory(src, dst, "agents")


def install_skills(
    source: Path | None = None,
    target: Path | None = None,
) -> list[str]:
    """Install skill definitions to ~/.claude/skills/.

    Returns list of installed skill filenames.
    """
    src = (source or ASSETS_DIR) / "skills"
    dst = target or SKILLS_DIR
    return _sync_directory(src, dst, "skills")


def install_all(
    assets_dir: Path | None = None,
    claude_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Install all agents and skills.

    Returns dict with 'agents' and 'skills' keys listing installed files.
    """
    base = assets_dir or ASSETS_DIR
    claude = claude_dir or CLAUDE_DIR

    return {
        "agents": install_agents(base, claude / "agents"),
        "skills": install_skills(base, claude / "skills"),
    }


def render_install_report(result: dict[str, list[str]]) -> None:
    """Display what was installed."""
    for category, files in result.items():
        if files:
            console.print(f"[green]✓[/green] {category}: {', '.join(files)}")
        else:
            console.print(f"[yellow]○[/yellow] {category}: nothing to install")
