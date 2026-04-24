"""Tests for devflow.cli — command registration and basic invocations."""

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


class TestDoCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["do", "--help"])
        assert result.exit_code == 0
        assert "Quick task on the current branch" in result.output

    def test_missing_description_shows_error(self) -> None:
        result = runner.invoke(app, ["do"])
        assert result.exit_code != 0


class TestFixDeprecated:
    def test_command_still_registered(self) -> None:
        result = runner.invoke(app, ["fix", "--help"])
        assert result.exit_code == 0

    def test_marked_deprecated(self) -> None:
        result = runner.invoke(app, ["fix", "--help"])
        assert "Deprecated" in result.output or "deprecated" in result.output


class TestRetryCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["retry", "--help"])
        assert result.exit_code == 0
        assert "Retry a failed feature" in result.output

    def test_missing_feature_id_shows_error(self) -> None:
        result = runner.invoke(app, ["retry"])
        assert result.exit_code != 0
