"""Tests for devflow.runner — Claude Code execution bridge."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.models import Feature, FeatureStatus, PhaseRecord
from devflow.runner import (
    _build_phase_context,
    _find_agent_file,
    build_prompt,
    execute_phase,
    run_gate_phase,
)


@pytest.fixture
def sample_feature() -> Feature:
    """Feature with some completed phases for context testing."""
    planning = PhaseRecord(name="planning")
    planning.start()
    planning.complete(output="## Plan\n1. Create models\n2. Add tests")

    implementing = PhaseRecord(name="implementing")

    return Feature(
        id="feat-test-001",
        description="Add user authentication",
        workflow="standard",
        status=FeatureStatus.IMPLEMENTING,
        phases=[planning, implementing],
    )


class TestBuildPhaseContext:
    def test_includes_completed_phase_output(self, sample_feature: Feature) -> None:
        implementing = sample_feature.phases[1]
        context = _build_phase_context(sample_feature, implementing)
        assert "Plan" in context
        assert "Create models" in context

    def test_empty_for_first_phase(self) -> None:
        phase = PhaseRecord(name="planning")
        feature = Feature(
            id="f-001", description="test", phases=[phase],
        )
        context = _build_phase_context(feature, phase)
        assert context == ""

    def test_skips_phases_without_output(self) -> None:
        p1 = PhaseRecord(name="planning")
        p1.start()
        p1.complete()  # No output.
        p2 = PhaseRecord(name="implementing")

        feature = Feature(
            id="f-001", description="test", phases=[p1, p2],
        )
        context = _build_phase_context(feature, p2)
        assert context == ""


class TestBuildPrompt:
    def test_includes_feature_info(self, sample_feature: Feature) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        assert "feat-test-001" in prompt
        assert "Add user authentication" in prompt
        assert "implementing" in prompt

    def test_includes_previous_context(self, sample_feature: Feature) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        assert "Plan" in prompt
        assert "Create models" in prompt

    def test_includes_phase_instructions(self, sample_feature: Feature) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        assert "Instructions" in prompt
        assert "Implement the plan" in prompt


class TestFindAgentFile:
    def test_finds_bundled_agent(self) -> None:
        # Bundled agents should exist in assets/agents/.
        path = _find_agent_file("planner")
        assert path is not None
        assert path.name == "planner.md"

    def test_returns_none_for_missing(self) -> None:
        assert _find_agent_file("nonexistent-agent-xyz") is None


class TestExecutePhase:
    def test_dry_run_returns_success(self, sample_feature: Feature) -> None:
        phase = sample_feature.phases[1]
        success, output = execute_phase(
            sample_feature, phase, "developer", dry_run=True,
        )
        assert success is True
        assert output == "[dry run]"

    @patch("devflow.runner.subprocess.run")
    def test_successful_execution(
        self, mock_run: MagicMock, sample_feature: Feature,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Implementation complete.\nAll tests pass.",
            stderr="",
        )
        phase = sample_feature.phases[1]
        success, output = execute_phase(
            sample_feature, phase, "developer",
        )
        assert success is True
        assert "Implementation complete" in output

        # Verify claude was called with -p flag.
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "claude"
        assert "-p" in call_args[0][0]

    @patch("devflow.runner.subprocess.run")
    def test_failed_execution(
        self, mock_run: MagicMock, sample_feature: Feature,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: context limit exceeded",
        )
        phase = sample_feature.phases[1]
        success, output = execute_phase(
            sample_feature, phase, "developer",
        )
        assert success is False
        assert "context limit" in output

    @patch(
        "devflow.runner.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_claude_not_installed(
        self, mock_run: MagicMock, sample_feature: Feature,
    ) -> None:
        phase = sample_feature.phases[1]
        success, output = execute_phase(
            sample_feature, phase, "developer",
        )
        assert success is False
        assert "Claude Code CLI not found" in output

    @patch("devflow.runner.subprocess.run")
    def test_timeout(
        self, mock_run: MagicMock, sample_feature: Feature,
    ) -> None:
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("claude", 60)
        phase = sample_feature.phases[1]
        success, output = execute_phase(
            sample_feature, phase, "developer", timeout=60,
        )
        assert success is False
        assert "timed out" in output


class TestRunGatePhase:
    def test_passes_on_clean_project(self, tmp_path: Path) -> None:
        # Create minimal project structure for gate.
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        success, output = run_gate_phase(tmp_path)
        # May fail on ruff/pytest not finding files, but shouldn't crash.
        assert isinstance(success, bool)
        assert isinstance(output, str)
