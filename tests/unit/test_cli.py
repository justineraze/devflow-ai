"""Tests for devflow.cli — command registration and basic invocations."""

from typer.testing import CliRunner

from devflow.cli import app

runner = CliRunner()


class TestVersionFlag:
    def test_version_flag_shows_version(self) -> None:
        from devflow import __version__

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"devflow {__version__}" in result.output


class TestDoCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["do", "--help"])
        assert result.exit_code == 0
        assert "Task on the current branch" in result.output

    def test_missing_description_shows_error(self) -> None:
        result = runner.invoke(app, ["do"])
        assert result.exit_code != 0

    def test_has_workflow_flag(self) -> None:
        result = runner.invoke(app, ["do", "--help"])
        assert "--workflow" in result.output


class TestBuildCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0

    def test_has_retry_flag(self) -> None:
        result = runner.invoke(app, ["build", "--help"])
        assert "--retry" in result.output

    def test_has_resume_flag(self) -> None:
        result = runner.invoke(app, ["build", "--help"])
        assert "--resume" in result.output

    def test_missing_description_without_retry_shows_error(self) -> None:
        result = runner.invoke(app, ["build"])
        assert result.exit_code != 0

    def test_retry_and_resume_conflict(self) -> None:
        result = runner.invoke(
            app, ["build", "--retry", "feat-001", "--resume", "feat-001", "feedback"],
        )
        assert result.exit_code != 0
        assert "Conflicting flags" in result.output


class TestStatusCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_has_log_flag(self) -> None:
        result = runner.invoke(app, ["status", "--help"])
        assert "--log" in result.output

    def test_has_metrics_flag(self) -> None:
        result = runner.invoke(app, ["status", "--help"])
        assert "--metrics" in result.output

    def test_has_archived_flag(self) -> None:
        result = runner.invoke(app, ["status", "--help"])
        assert "--archived" in result.output


class TestInstallCommand:
    def test_command_is_registered(self) -> None:
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0

    def test_has_check_flag(self) -> None:
        result = runner.invoke(app, ["install", "--help"])
        assert "--check" in result.output

    def test_has_linear_team_flag(self) -> None:
        result = runner.invoke(app, ["install", "--help"])
        assert "--linear-team" in result.output


class TestDeprecatedCommands:
    """Deprecated shims still work but show a deprecation hint."""

    def test_fix_still_registered(self) -> None:
        result = runner.invoke(app, ["fix", "--help"])
        assert result.exit_code == 0

    def test_retry_still_registered(self) -> None:
        result = runner.invoke(app, ["retry", "--help"])
        assert result.exit_code == 0

    def test_log_still_registered(self) -> None:
        result = runner.invoke(app, ["log", "--help"])
        assert result.exit_code == 0

    def test_doctor_still_registered(self) -> None:
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0

    def test_version_still_registered(self) -> None:
        result = runner.invoke(app, ["version", "--help"])
        assert result.exit_code == 0
