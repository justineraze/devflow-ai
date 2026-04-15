"""Tests for devflow.setup.install — agent and skill sync."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from devflow.setup.install import install_agents, install_all, install_hook, install_skills

HOOK_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "assets" / "hooks" / "devflow-post-compact.sh"
)


def _create_assets(tmp_path: Path) -> Path:
    """Create a fake assets directory with test .md files and hook script."""
    assets = tmp_path / "assets"
    (assets / "agents").mkdir(parents=True)
    (assets / "skills").mkdir(parents=True)
    (assets / "hooks").mkdir(parents=True)
    (assets / "agents" / "planner.md").write_text("# Planner")
    (assets / "agents" / "developer.md").write_text("# Developer")
    (assets / "skills" / "build.md").write_text("# Build")
    (assets / "skills" / "gsd.md").write_text("# GSD")
    # Copy the real hook script so install_hook() has something to copy.
    if HOOK_SCRIPT.exists():
        import shutil
        shutil.copy2(HOOK_SCRIPT, assets / "hooks" / "devflow-post-compact.sh")
    else:
        (assets / "hooks" / "devflow-post-compact.sh").write_text("#!/usr/bin/env bash\n")
    return assets


class TestInstallAgents:
    def test_copies_agent_files(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        target = tmp_path / "claude" / "agents"
        synced = install_agents(assets, target)
        assert set(synced) == {"developer.md", "planner.md"}
        assert (target / "planner.md").exists()
        assert (target / "planner.md").read_text() == "# Planner"

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        target = tmp_path / "new" / "deep" / "agents"
        install_agents(assets, target)
        assert target.exists()

    def test_missing_source_returns_empty(self, tmp_path: Path) -> None:
        source = tmp_path / "nonexistent"
        target = tmp_path / "target"
        synced = install_agents(source, target)
        assert synced == []


class TestInstallSkills:
    def test_copies_skill_files(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        target = tmp_path / "claude" / "skills"
        synced = install_skills(assets, target)
        assert set(synced) == {"build.md", "gsd.md"}

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        target = tmp_path / "claude" / "skills"
        target.mkdir(parents=True)
        (target / "build.md").write_text("old content")
        install_skills(assets, target)
        assert (target / "build.md").read_text() == "# Build"


class TestInstallHook:
    def test_copies_script_to_hooks_dir(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        install_hook(assets, settings, hooks_dir)
        assert (hooks_dir / "devflow-post-compact.sh").exists()

    def test_script_has_exec_bit(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        install_hook(assets, settings, hooks_dir)
        mode = (hooks_dir / "devflow-post-compact.sh").stat().st_mode
        assert mode & stat.S_IXUSR, "owner exec bit should be set"

    def test_creates_settings_json_when_absent(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        install_hook(assets, settings, hooks_dir)
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "hooks" in data
        assert "PostCompact" in data["hooks"]
        assert len(data["hooks"]["PostCompact"]) == 1

    def test_preserves_unrelated_keys(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"model": "sonnet", "permissions": ["read"]}))

        install_hook(assets, settings, hooks_dir)

        data = json.loads(settings.read_text())
        assert data["model"] == "sonnet"
        assert data["permissions"] == ["read"]

    def test_preserves_other_post_compact_entries(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        existing_entry = {"type": "command", "command": "/usr/local/bin/other-hook.sh"}
        settings.write_text(json.dumps({"hooks": {"PostCompact": [existing_entry]}}))

        install_hook(assets, settings, hooks_dir)

        data = json.loads(settings.read_text())
        entries = data["hooks"]["PostCompact"]
        assert len(entries) == 2
        commands = [e["command"] for e in entries]
        assert "/usr/local/bin/other-hook.sh" in commands

    def test_idempotent_no_duplicate_entry(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"

        install_hook(assets, settings, hooks_dir)
        install_hook(assets, settings, hooks_dir)

        data = json.loads(settings.read_text())
        entries = data["hooks"]["PostCompact"]
        assert len(entries) == 1

    def test_returns_hook_script_name(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        hooks_dir = tmp_path / "claude" / "hooks"
        settings = tmp_path / "claude" / "settings.json"
        name = install_hook(assets, settings, hooks_dir)
        assert name == "devflow-post-compact.sh"


class TestInstallAll:
    def test_installs_agents_and_skills(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        claude = tmp_path / "claude"
        result = install_all(assets, claude)
        assert len(result["agents"]) == 2
        assert len(result["skills"]) == 2
        assert (claude / "agents" / "planner.md").exists()
        assert (claude / "skills" / "build.md").exists()

    def test_includes_hook_in_result(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        claude = tmp_path / "claude"
        result = install_all(assets, claude)
        assert result["hook"] == ["devflow-post-compact.sh"]

    def test_settings_json_has_post_compact_entry(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        claude = tmp_path / "claude"
        install_all(assets, claude)
        settings = claude / "settings.json"
        data = json.loads(settings.read_text())
        assert "PostCompact" in data["hooks"]
        assert len(data["hooks"]["PostCompact"]) == 1
