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


class TestRetryCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["retry", "--help"])
        assert result.exit_code == 0
        assert "Retry a failed feature" in result.output

    def test_missing_feature_id_shows_error(self) -> None:
        result = runner.invoke(app, ["retry"])
        assert result.exit_code != 0
