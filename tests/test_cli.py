"""Tests for devflow.cli — command registration and basic invocations."""

import json

from typer.testing import CliRunner

from devflow.cli import app

runner = CliRunner()


class TestVersionCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["version", "--help"])
        assert result.exit_code == 0
        assert "Show the current devflow version" in result.output

    def test_shows_version(self) -> None:
        from devflow import __version__

        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert f"devflow {__version__}" in result.output


class TestAboutCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["about", "--help"])
        assert result.exit_code == 0
        assert "Show author, repository URL, and license" in result.output

    def test_shows_metadata(self) -> None:
        result = runner.invoke(app, ["about"])
        assert result.exit_code == 0
        assert "Justine Raze" in result.output
        assert "github.com/JustineRaze/devflow-ai" in result.output
        assert "MIT" in result.output

    def test_shows_version(self) -> None:
        from devflow import __version__

        result = runner.invoke(app, ["about"])
        assert f"devflow {__version__}" in result.output


class TestStatusJsonFlag:
    def test_json_flag_empty_state(self, tmp_path, monkeypatch) -> None:
        """--json with no features returns an empty JSON list."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_json_flag_with_features(self, tmp_path, monkeypatch) -> None:
        """--json outputs feature data as JSON array."""
        from devflow.models import Feature, WorkflowState
        from devflow.workflow import ensure_devflow_dir, save_state

        monkeypatch.chdir(tmp_path)
        ensure_devflow_dir(tmp_path)
        state = WorkflowState()
        feat = Feature(id="f-001", description="test feature")
        state.add_feature(feat)
        save_state(state, tmp_path)

        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "f-001"
        assert data[0]["description"] == "test feature"

    def test_json_flag_single_feature(self, tmp_path, monkeypatch) -> None:
        """--json with a feature ID outputs that feature as JSON object."""
        from devflow.models import Feature, WorkflowState
        from devflow.workflow import ensure_devflow_dir, save_state

        monkeypatch.chdir(tmp_path)
        ensure_devflow_dir(tmp_path)
        state = WorkflowState()
        feat = Feature(id="f-002", description="specific feature")
        state.add_feature(feat)
        save_state(state, tmp_path)

        result = runner.invoke(app, ["status", "f-002", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "f-002"
        assert data["description"] == "specific feature"

    def test_json_flag_feature_not_found(self, tmp_path, monkeypatch) -> None:
        """--json with unknown feature ID returns error JSON and exit code 1."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status", "nope", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data


class TestRetryCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["retry", "--help"])
        assert result.exit_code == 0
        assert "Retry a failed feature" in result.output

    def test_missing_feature_id_shows_error(self) -> None:
        result = runner.invoke(app, ["retry"])
        assert result.exit_code != 0
