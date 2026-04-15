"""Install and sync agents/skills to ~/.claude/ directories."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from devflow.ui.console import console

# Package assets directory (relative to this file).
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "assets"

# Default Claude Code directories.
CLAUDE_DIR = Path.home() / ".claude"
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"
HOOKS_DIR = CLAUDE_DIR / "hooks"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
HOOK_SCRIPT_NAME = "devflow-post-compact.sh"


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


def install_hook(
    source: Path | None = None,
    settings_file: Path | None = None,
    hooks_dir: Path | None = None,
) -> str:
    """Install the PostCompact hook script and register it in settings.json.

    Copies ``assets/hooks/devflow-post-compact.sh`` to ``hooks_dir``, sets the
    executable bit, then upserts a ``PostCompact`` entry in ``settings_file``
    matching by command path (idempotent — no duplicate entries).

    Returns the installed script filename.
    """
    from devflow.setup._settings import load_settings, write_settings_atomic

    src = (source or ASSETS_DIR) / "hooks" / HOOK_SCRIPT_NAME
    dst_dir = hooks_dir or HOOKS_DIR
    dst = dst_dir / HOOK_SCRIPT_NAME
    cfg = settings_file or SETTINGS_FILE

    # Copy script.
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    # Ensure it is executable (owner + group + other).
    current = dst.stat().st_mode
    dst.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Merge PostCompact entry into settings.json.
    data, err = load_settings(cfg)
    if err:
        raise RuntimeError(
            f"Refusing to rewrite settings.json: {err}. "
            "Fix the JSON manually, then re-run `devflow install`."
        )
    hook_command = str(dst.resolve())

    hooks_section: dict = data.setdefault("hooks", {})
    post_compact: list = hooks_section.setdefault("PostCompact", [])

    # Upsert: only add if not already present (match by command path).
    already_registered = any(
        entry.get("command") == hook_command
        for entry in post_compact
        if isinstance(entry, dict)
    )
    if not already_registered:
        post_compact.append({"type": "command", "command": hook_command})

    write_settings_atomic(cfg, data)
    return HOOK_SCRIPT_NAME


def install_all(
    assets_dir: Path | None = None,
    claude_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Install all agents, skills and the PostCompact hook.

    Returns dict with 'agents', 'skills', and 'hook' keys listing installed files.
    """
    base = assets_dir or ASSETS_DIR
    claude = claude_dir or CLAUDE_DIR

    return {
        "agents": install_agents(base, claude / "agents"),
        "skills": install_skills(base, claude / "skills"),
        "hook": [install_hook(base, claude / "settings.json", claude / "hooks")],
    }


def render_install_report(result: dict[str, list[str]]) -> None:
    """Display what was installed."""
    for category, files in result.items():
        if files:
            console.print(f"[green]✓[/green] {category}: {', '.join(files)}")
        else:
            console.print(f"[yellow]○[/yellow] {category}: nothing to install")
