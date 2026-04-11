"""Tests for devflow.install — agent and skill sync."""

from pathlib import Path

from devflow.install import install_agents, install_all, install_skills


def _create_assets(tmp_path: Path) -> Path:
    """Create a fake assets directory with test .md files."""
    assets = tmp_path / "assets"
    (assets / "agents").mkdir(parents=True)
    (assets / "skills").mkdir(parents=True)
    (assets / "agents" / "planner.md").write_text("# Planner")
    (assets / "agents" / "developer.md").write_text("# Developer")
    (assets / "skills" / "build.md").write_text("# Build")
    (assets / "skills" / "gsd.md").write_text("# GSD")
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


class TestInstallAll:
    def test_installs_agents_and_skills(self, tmp_path: Path) -> None:
        assets = _create_assets(tmp_path)
        claude = tmp_path / "claude"
        result = install_all(assets, claude)
        assert len(result["agents"]) == 2
        assert len(result["skills"]) == 2
        assert (claude / "agents" / "planner.md").exists()
        assert (claude / "skills" / "build.md").exists()
