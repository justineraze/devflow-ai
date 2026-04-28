"""Tests for devflow.core.config — unified config loading and migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from devflow.core.config import (
    DevflowConfig,
    GateConfig,
    LinearConfig,
    load_config,
    save_config,
)


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".devflow").mkdir()
    return tmp_path


class TestDefaults:
    def test_defaults(self) -> None:
        config = DevflowConfig()
        assert config.stack is None
        assert config.base_branch == "main"
        assert config.gate.lint is None
        assert config.gate.test is None
        assert config.linear.team is None
        assert config.backend == "claude"

    def test_load_returns_defaults_when_no_file(self, project_dir: Path) -> None:
        config = load_config(project_dir)
        assert config.stack is None
        assert config.base_branch == "main"
        assert config.backend == "claude"


class TestLoadConfig:
    def test_loads_full_config(self, project_dir: Path) -> None:
        data = {
            "stack": "python",
            "base_branch": "develop",
            "gate": {"lint": "make lint", "test": "make test"},
            "linear": {"team": "ABC"},
            "backend": "claude",
        }
        (project_dir / ".devflow" / "config.yaml").write_text(yaml.dump(data))

        config = load_config(project_dir)
        assert config.stack == "python"
        assert config.base_branch == "develop"
        assert config.gate.lint == "make lint"
        assert config.gate.test == "make test"
        assert config.linear.team == "ABC"
        assert config.backend == "claude"

    def test_loads_partial_config(self, project_dir: Path) -> None:
        (project_dir / ".devflow" / "config.yaml").write_text("stack: typescript\n")
        config = load_config(project_dir)
        assert config.stack == "typescript"
        assert config.base_branch == "main"
        assert config.gate.lint is None

    def test_ignores_unknown_keys(self, project_dir: Path) -> None:
        (project_dir / ".devflow" / "config.yaml").write_text(
            "stack: python\nfuture_key: whatever\n"
        )
        config = load_config(project_dir)
        assert config.stack == "python"


class TestSaveConfig:
    def test_roundtrip(self, project_dir: Path) -> None:
        config = DevflowConfig(
            stack="python",
            base_branch="develop",
            gate=GateConfig(lint="ruff check ."),
            linear=LinearConfig(team="XYZ"),
        )
        save_config(config, project_dir)

        loaded = load_config(project_dir)
        assert loaded.stack == "python"
        assert loaded.base_branch == "develop"
        assert loaded.gate.lint == "ruff check ."
        assert loaded.linear.team == "XYZ"

    def test_omits_defaults(self, project_dir: Path) -> None:
        """Default values should not be written to keep the YAML clean."""
        config = DevflowConfig(stack="python")
        save_config(config, project_dir)

        raw = yaml.safe_load(
            (project_dir / ".devflow" / "config.yaml").read_text()
        )
        assert raw == {"version": 1, "stack": "python"}
        assert "base_branch" not in raw
        assert "backend" not in raw
        assert "gate" not in raw

    def test_empty_config_writes_version_only(self, project_dir: Path) -> None:
        save_config(DevflowConfig(), project_dir)
        raw = yaml.safe_load(
            (project_dir / ".devflow" / "config.yaml").read_text()
        )
        assert raw == {"version": 1}


class TestMigrateGateYaml:
    def test_migrates_gate_yaml_into_config(self, project_dir: Path) -> None:
        """Legacy gate.yaml should be absorbed and deleted."""
        (project_dir / ".devflow" / "gate.yaml").write_text(
            "lint: make check\ntest: make test\n"
        )

        config = load_config(project_dir)
        assert config.gate.lint == "make check"
        assert config.gate.test == "make test"
        # gate.yaml should be deleted.
        assert not (project_dir / ".devflow" / "gate.yaml").exists()
        # config.yaml should now exist with the merged data.
        assert (project_dir / ".devflow" / "config.yaml").is_file()

    def test_config_yaml_takes_precedence_over_gate_yaml(self, project_dir: Path) -> None:
        """Existing config.yaml gate values are not overwritten by gate.yaml."""
        (project_dir / ".devflow" / "config.yaml").write_text(
            yaml.dump({"gate": {"lint": "custom lint"}})
        )
        (project_dir / ".devflow" / "gate.yaml").write_text("lint: old lint\n")

        config = load_config(project_dir)
        assert config.gate.lint == "custom lint"


class TestMigrateStateJson:
    def test_migrates_state_json_config_fields(self, project_dir: Path) -> None:
        """Legacy config fields in state.json should be migrated."""
        state_data = {
            "version": 1,
            "stack": "python",
            "base_branch": "develop",
            "linear_team_id": "ABC",
            "features": {},
        }
        (project_dir / ".devflow" / "state.json").write_text(json.dumps(state_data))

        config = load_config(project_dir)
        assert config.stack == "python"
        assert config.base_branch == "develop"
        assert config.linear.team == "ABC"

    def test_config_yaml_takes_precedence_over_state_json(self, project_dir: Path) -> None:
        """Existing config.yaml values are not overwritten by state.json."""
        (project_dir / ".devflow" / "config.yaml").write_text(
            yaml.dump({"stack": "typescript"})
        )
        state_data = {
            "version": 1, "stack": "python", "features": {},
        }
        (project_dir / ".devflow" / "state.json").write_text(json.dumps(state_data))

        config = load_config(project_dir)
        assert config.stack == "typescript"

    def test_no_migration_when_state_has_no_config_fields(self, project_dir: Path) -> None:
        state_data = {"version": 1, "features": {}}
        (project_dir / ".devflow" / "state.json").write_text(json.dumps(state_data))

        config = load_config(project_dir)
        assert config.stack is None
        assert config.base_branch == "main"
