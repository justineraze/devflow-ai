"""Tests for devflow.orchestration.runner — prompt building and Claude Code execution."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.models import Feature, FeatureStatus, PhaseRecord
from devflow.integrations.gate import run_gate_phase
from devflow.orchestration.runner import (
    _build_phase_context,
    _find_agent_file,
    _find_skill_file,
    _load_agent_prompt,
    _load_skills_for_phase,
    _parse_extends,
    build_prompt,
    execute_phase,
)


@pytest.fixture
def sample_feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Feature:
    """Feature with some completed phases — artifact written to isolated tmp dir."""
    from devflow.core.artifacts import save_phase_output

    monkeypatch.chdir(tmp_path)

    plan_output = "## Plan\n1. Create models\n2. Add tests"
    save_phase_output("feat-test-001", "planning", plan_output)

    planning = PhaseRecord(name="planning")
    planning.start()
    planning.complete()

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
    @patch("devflow.orchestration.runner.subprocess.Popen")
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
        success, output, _metrics = execute_phase(sample_feature, phase, "developer")
        assert success is True
        assert "done" in output

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    @patch("devflow.orchestration.runner.subprocess.Popen")
    def test_failed_execution(
        self, mock_popen: MagicMock, sample_feature: Feature,
    ) -> None:
        mock_popen.return_value = _mock_popen(
            returncode=1, stdout_lines=[], stderr="Error: something broke",
        )
        phase = sample_feature.phases[1]
        success, output, _metrics = execute_phase(sample_feature, phase, "developer")
        assert success is False
        assert "something broke" in output

    @patch("devflow.orchestration.runner.subprocess.Popen", side_effect=FileNotFoundError)
    def test_claude_not_installed(
        self, mock_popen: MagicMock, sample_feature: Feature,
    ) -> None:
        phase = sample_feature.phases[1]
        success, output, _metrics = execute_phase(sample_feature, phase, "developer")
        assert success is False
        assert "Claude Code CLI not found" in output


class TestRunGatePhase:
    def test_passes_on_clean_project(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        success, output, _metrics = run_gate_phase(tmp_path)
        assert isinstance(success, bool)
        assert isinstance(output, str)


class TestSkillInjection:
    def test_finds_bundled_context_skill(self) -> None:
        path = _find_skill_file("devflow-context")
        assert path is not None
        assert path.name == "devflow-context.md"

    def test_returns_none_for_missing_skill(self) -> None:
        assert _find_skill_file("nonexistent-skill-xyz") is None

    def test_implementing_phase_loads_relevant_skills(self) -> None:
        content = _load_skills_for_phase("implementing")
        assert "Context Discipline" in content
        assert "Incremental Build" in content
        assert "TDD" in content
        # devflow-refactor is scoped to reviewing only — not here.
        assert "Refactor First" not in content

    def test_reviewing_phase_keeps_refactor_first(self) -> None:
        content = _load_skills_for_phase("reviewing")
        assert "Refactor First" in content
        assert "Code Review" in content

    def test_planning_phase_loads_relevant_skills(self) -> None:
        content = _load_skills_for_phase("planning")
        assert "Context Discipline" in content
        assert "Planning Rigor" in content

    def test_unknown_phase_only_loads_always_on(self) -> None:
        content = _load_skills_for_phase("unknown-phase")
        assert "Context Discipline" in content

    def test_build_prompt_includes_skills_section(
        self, sample_feature: Feature,
    ) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        assert "Skills (discipline rules)" in prompt
        assert "Context Discipline" in prompt


class TestParseExtends:
    def test_returns_parent_name_from_frontmatter(self) -> None:
        path = _find_agent_file("developer-python")
        assert _parse_extends(path) == "developer"

    def test_returns_none_for_agent_without_extends(self) -> None:
        path = _find_agent_file("developer")
        assert _parse_extends(path) is None

    def test_returns_none_for_missing_path(self) -> None:
        assert _parse_extends(None) is None

    def test_returns_none_for_no_frontmatter(self, tmp_path: Path) -> None:
        md = tmp_path / "agent.md"
        md.write_text("# No frontmatter\nJust content.")
        assert _parse_extends(md) is None


class TestLoadAgentPrompt:
    def test_specialist_loads_base_then_delta(self) -> None:
        prompt = _load_agent_prompt("developer-python")
        # Base developer content comes first.
        idx_base = prompt.find("# Agent: Developer\n")
        idx_spec = prompt.find("# Agent: Developer — Python Specialist")
        assert idx_base >= 0, "base developer content missing"
        assert idx_spec > idx_base, "specialist should come after base"

    def test_base_agent_loads_without_duplication(self) -> None:
        prompt = _load_agent_prompt("developer")
        assert prompt.count("# Agent: Developer") == 1

    def test_non_extending_agent_loads_normally(self) -> None:
        prompt = _load_agent_prompt("planner")
        assert "Planner" in prompt
        # Should not contain developer base content.
        assert "# Agent: Developer\n" not in prompt

    def test_all_specialists_extend_developer(self) -> None:
        for name in ("developer-python", "developer-typescript",
                      "developer-php", "developer-frontend"):
            path = _find_agent_file(name)
            assert _parse_extends(path) == "developer", f"{name} should extend developer"

    def test_system_prompt_with_specialist_includes_base(self) -> None:
        from devflow.orchestration.runner import build_system_prompt

        system = build_system_prompt("implementing", "developer-python")
        assert "# Agent: Developer\n" in system
        assert "Python Specialist" in system


class TestPromptSplit:
    def test_system_prompt_contains_skills_and_agent(
        self, sample_feature: Feature,
    ) -> None:
        from devflow.orchestration.runner import build_system_prompt

        system = build_system_prompt("implementing", "developer")
        assert "Skills (discipline rules)" in system
        assert "Context Discipline" in system
        assert "Agent role" in system

    def test_user_prompt_contains_task_not_skills(
        self, sample_feature: Feature,
    ) -> None:
        from devflow.orchestration.runner import build_user_prompt

        phase = sample_feature.phases[1]
        user = build_user_prompt(sample_feature, phase)
        assert "Current task" in user
        assert "feat-test-001" in user
        # Skills should NOT be in the user prompt anymore.
        assert "Skills (discipline rules)" not in user
        assert "Context Discipline" not in user

    def test_build_prompt_still_combines_both(
        self, sample_feature: Feature,
    ) -> None:
        phase = sample_feature.phases[1]
        prompt = build_prompt(sample_feature, phase, "developer")
        # Backward-compat: the combined prompt still has everything.
        assert "Skills (discipline rules)" in prompt
        assert "Current task" in prompt


