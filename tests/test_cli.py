"""Tests for devflow.cli — command registration and basic invocations."""

from typer.testing import CliRunner

from devflow.cli import app

runner = CliRunner()


class TestRetryCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["retry", "--help"])
        assert result.exit_code == 0
        assert "Retry a failed feature" in result.output

    def test_missing_feature_id_shows_error(self) -> None:
        result = runner.invoke(app, ["retry"])
        assert result.exit_code != 0
