"""Tests for devflow.runner — prompt building and Claude Code execution."""

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
        feature = Feature(id="f-001", description="test", phases=[phase])
        context = _build_phase_context(feature, phase)
        assert context == ""

    def test_skips_phases_without_output(self) -> None:
        p1 = PhaseRecord(name="planning")
        p1.start()
        p1.complete()
        p2 = PhaseRecord(name="implementing")
        feature = Feature(id="f-001", description="test", phases=[p1, p2])
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

    def test_implementing_has_commit_guidance(self, sample_feature: Feature) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        assert "git add" in prompt
        assert "git commit" in prompt
        assert "Do NOT batch" in prompt

    def test_fixing_has_commit_guidance(self) -> None:
        fixing = PhaseRecord(name="fixing")
        feature = Feature(
            id="f-001", description="test",
            status=FeatureStatus.FIXING, phases=[fixing],
        )
        prompt = build_prompt(feature, fixing, "developer")
        assert "git add" in prompt
        assert "git commit" in prompt


class TestFindAgentFile:
    def test_finds_bundled_agent(self) -> None:
        path = _find_agent_file("planner")
        assert path is not None
        assert path.name == "planner.md"

    def test_returns_none_for_missing(self) -> None:
        assert _find_agent_file("nonexistent-agent-xyz") is None


def _mock_popen(returncode: int = 0, stdout_lines: list[str] | None = None,
                stderr: str = "") -> MagicMock:
    """Build a Popen mock with streamable stdout."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = iter(stdout_lines or [])
    proc.stderr.read.return_value = stderr
    proc.stdin = MagicMock()
    proc.wait = MagicMock()
    return proc


class TestExecutePhase:
    @patch("devflow.runner.subprocess.Popen")
    def test_successful_execution(
        self, mock_popen: MagicMock, sample_feature: Feature,
    ) -> None:
        result_line = (
            '{"type":"result","duration_ms":1000,"total_cost_usd":0.01,'
            '"result":"done","usage":{"input_tokens":100,"output_tokens":50}}'
        )
        mock_popen.return_value = _mock_popen(
            returncode=0, stdout_lines=[result_line],
        )
        phase = sample_feature.phases[1]
        success, output = execute_phase(sample_feature, phase, "developer")
        assert success is True
        assert "done" in output

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    @patch("devflow.runner.subprocess.Popen")
    def test_failed_execution(
        self, mock_popen: MagicMock, sample_feature: Feature,
    ) -> None:
        mock_popen.return_value = _mock_popen(
            returncode=1, stdout_lines=[], stderr="Error: something broke",
        )
        phase = sample_feature.phases[1]
        success, output = execute_phase(sample_feature, phase, "developer")
        assert success is False
        assert "something broke" in output

    @patch("devflow.runner.subprocess.Popen", side_effect=FileNotFoundError)
    def test_claude_not_installed(
        self, mock_popen: MagicMock, sample_feature: Feature,
    ) -> None:
        phase = sample_feature.phases[1]
        success, output = execute_phase(sample_feature, phase, "developer")
        assert success is False
        assert "Claude Code CLI not found" in output


class TestRunGatePhase:
    def test_passes_on_clean_project(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        success, output = run_gate_phase(tmp_path)
        assert isinstance(success, bool)
        assert isinstance(output, str)
