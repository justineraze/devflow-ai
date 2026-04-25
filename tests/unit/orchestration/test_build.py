"""Tests for devflow.orchestration.build — orchestration logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.metrics import PhaseMetrics
from devflow.core.models import FeatureStatus, PhaseStatus
from devflow.core.workflow import load_state, save_state
from devflow.orchestration.build import execute_build_loop
from devflow.orchestration.lifecycle import (
    _generate_feature_id,
    resume_build,
    retry_build,
    start_build,
    start_fix,
)
from devflow.orchestration.model_routing import get_phase_agent
from devflow.orchestration.phase_exec import (
    complete_phase,
    fail_phase,
    run_phase,
)
from devflow.orchestration.plan_parser import (
    parse_plan_module,
    parse_plan_title,
    parse_plan_type,
)

_PHASE_OK = (True, "done", PhaseMetrics())


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestParsePlanModule:
    def test_extracts_module_name(self) -> None:
        plan = "### Scope\n- Type: extension\n- Module: runner\n"
        assert parse_plan_module(plan) == "runner"

    def test_returns_none_when_absent(self) -> None:
        plan = "### Scope\n- Type: extension\n- Complexity: low\n"
        assert parse_plan_module(plan) is None

    def test_ignores_extra_words_after_module(self) -> None:
        plan = "- Module: gate (parallel execution)\n"
        assert parse_plan_module(plan) == "gate"

    def test_empty_string_returns_none(self) -> None:
        assert parse_plan_module("") is None


class TestParsePlanTitle:
    def test_extracts_title_after_em_dash(self) -> None:
        plan = "## Plan: feat-001 — Document Pydantic vs dataclass convention\n"
        assert parse_plan_title(plan) == "Document Pydantic vs dataclass convention"

    def test_extracts_title_after_en_dash(self) -> None:
        plan = "## Plan: feat-001 – Move console to core\n"
        assert parse_plan_title(plan) == "Move console to core"

    def test_extracts_title_after_hyphen(self) -> None:
        plan = "## Plan: feat-001 - Add metrics display\n"
        assert parse_plan_title(plan) == "Add metrics display"

    def test_returns_none_when_absent(self) -> None:
        plan = "### Scope\n- Type: extension\n"
        assert parse_plan_title(plan) is None

    def test_returns_none_for_empty(self) -> None:
        assert parse_plan_title("") is None

    def test_strips_whitespace(self) -> None:
        plan = "## Plan: feat-001 —   Add caching layer  \n"
        assert parse_plan_title(plan) == "Add caching layer"


class TestParsePlanType:
    def test_maps_new_feature_to_feat(self) -> None:
        plan = "- Type: new-feature\n"
        assert parse_plan_type(plan) == "feat"

    def test_maps_extension_to_feat(self) -> None:
        plan = "- Type: extension\n"
        assert parse_plan_type(plan) == "feat"

    def test_maps_bugfix_to_fix(self) -> None:
        plan = "- Type: bugfix\n"
        assert parse_plan_type(plan) == "fix"

    def test_maps_refactor(self) -> None:
        plan = "- Type: refactor\n"
        assert parse_plan_type(plan) == "refactor"

    def test_maps_docs(self) -> None:
        plan = "- Type: docs\n"
        assert parse_plan_type(plan) == "docs"

    def test_maps_ci(self) -> None:
        plan = "- Type: ci\n"
        assert parse_plan_type(plan) == "ci"

    def test_returns_none_when_absent(self) -> None:
        plan = "- Module: runner\n"
        assert parse_plan_type(plan) is None

    def test_returns_none_for_unknown_type(self) -> None:
        plan = "- Type: banana\n"
        assert parse_plan_type(plan) is None

    def test_returns_none_for_empty(self) -> None:
        assert parse_plan_type("") is None


class TestGenerateFeatureId:
    def test_generates_slug_from_description(self) -> None:
        fid = _generate_feature_id("Add user authentication")
        assert fid.startswith("feat-add-user-authentication-")

    def test_handles_empty_description(self) -> None:
        fid = _generate_feature_id("")
        assert fid.startswith("feat-")

    def test_strips_special_characters(self) -> None:
        fid = _generate_feature_id("Fix bug #123 — urgent!")
        assert "#" not in fid
        assert "!" not in fid


class TestStartBuild:
    def test_creates_feature_in_state(self, project_dir: Path) -> None:
        feature = start_build("Add dark mode", "standard", project_dir)
        assert feature.description == "Add dark mode"
        assert feature.workflow == "standard"
        state = load_state(project_dir)
        assert state.get_feature(feature.id) is not None

    def test_avoids_id_collision(self, project_dir: Path) -> None:
        f1 = start_build("test feature", "standard", project_dir)
        f2 = start_build("test feature", "standard", project_dir)
        assert f1.id != f2.id

    def test_creates_phases_from_workflow(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert len(feature.phases) == 4
        assert feature.phases[0].name == "planning"


class TestStartFix:
    def test_uses_quick_workflow(self, project_dir: Path) -> None:
        feature = start_fix("Fix broken login", project_dir)
        assert feature.workflow == "quick"
        assert len(feature.phases) == 2
        assert feature.phases[0].name == "implementing"


class TestResumeBuild:
    def test_resumes_existing_feature(self, project_dir: Path) -> None:
        original = start_build("test", "standard", project_dir)
        resumed = resume_build(original.id, project_dir)
        assert resumed is not None
        assert resumed.id == original.id

    def test_returns_none_for_missing(self, project_dir: Path) -> None:
        assert resume_build("nonexistent", project_dir) is None

    def test_returns_none_for_done(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        tracked.status = FeatureStatus.DONE
        save_state(state, project_dir)
        assert resume_build(feature.id, project_dir) is None

    def test_recovers_failed_feature(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        # Advance to implementing, then fail it.
        run_phase(feature, project_dir)  # planning
        complete_phase(feature.id, "planning", "plan", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        run_phase(tracked, project_dir)  # implementing
        fail_phase(feature.id, "implementing", "broke", project_dir)

        # Resume should recover.
        resumed = resume_build(feature.id, project_dir)
        assert resumed is not None
        assert resumed.status != FeatureStatus.FAILED

        # The failed phase should be pending again.
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        impl_phase = next(p for p in tracked.phases if p.name == "implementing")
        assert impl_phase.status == PhaseStatus.PENDING


class TestRetryBuild:
    def test_retries_failed_feature(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        # Advance to implementing, then fail it.
        run_phase(feature, project_dir)  # planning
        complete_phase(feature.id, "planning", "plan", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        run_phase(tracked, project_dir)  # implementing
        fail_phase(feature.id, "implementing", "broke", project_dir)

        retried = retry_build(feature.id, project_dir)
        assert retried is not None
        assert retried.status != FeatureStatus.FAILED

        # The failed phase should be pending again.
        impl_phase = next(p for p in retried.phases if p.name == "implementing")
        assert impl_phase.status == PhaseStatus.PENDING

    def test_returns_none_for_non_failed(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert retry_build(feature.id, project_dir) is None

    def test_returns_none_for_unknown(self, project_dir: Path) -> None:
        assert retry_build("nonexistent", project_dir) is None


class TestRunPhase:
    def test_advances_to_first_phase(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        phase = run_phase(feature, project_dir)
        assert phase is not None
        assert phase.name == "planning"
        assert phase.status == PhaseStatus.IN_PROGRESS

    def test_returns_none_when_all_done(self, project_dir: Path) -> None:
        feature = start_build("test", "quick", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        for p in tracked.phases:
            p.start()
            p.complete()
        save_state(state, project_dir)
        assert run_phase(feature, project_dir) is None


class TestCompletePhase:
    def test_marks_phase_done(self, project_dir: Path) -> None:
        from devflow.core.artifacts import load_phase_output

        feature = start_build("test", "standard", project_dir)
        run_phase(feature, project_dir)
        complete_phase(feature.id, "planning", "plan complete", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.phases[0].status == PhaseStatus.DONE
        # output is cleared from state.json to avoid duplication
        assert tracked.phases[0].output == ""
        # but the content is safely stored as an artifact
        assert load_phase_output(feature.id, "planning", project_dir) == "plan complete"


class TestFailPhase:
    def test_marks_phase_and_feature_failed(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        run_phase(feature, project_dir)
        fail_phase(feature.id, "planning", "timeout", project_dir)
        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.phases[0].status == PhaseStatus.FAILED
        assert tracked.status == FeatureStatus.FAILED


class TestGetPhaseAgent:
    def _set_stack(self, project_dir: Path, stack: str) -> None:
        from devflow.core.config import DevflowConfig, save_config
        config = DevflowConfig(stack=stack)
        save_config(config, project_dir)

    def test_returns_developer_python_for_python_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        self._set_stack(project_dir, "python")
        assert get_phase_agent(feature, "implementing", project_dir) == "developer-python"

    def test_returns_developer_typescript_for_ts_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        self._set_stack(project_dir, "typescript")
        assert get_phase_agent(feature, "implementing", project_dir) == "developer-typescript"

    def test_returns_developer_when_no_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        assert get_phase_agent(feature, "implementing", project_dir) == "developer"

    def test_non_developer_agent_unchanged_with_stack(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        self._set_stack(project_dir, "python")
        assert get_phase_agent(feature, "planning", project_dir) == "planner"

    def test_stack_kwarg_avoids_state_read(self, project_dir: Path) -> None:
        """Passing stack= directly skips load_config — no config.yaml needed."""
        feature = start_build("test", "standard", project_dir)
        result = get_phase_agent(feature, "implementing", stack="python")
        assert result == "developer-python"

    def test_stack_none_falls_back_to_config(self, project_dir: Path) -> None:
        feature = start_build("test", "standard", project_dir)
        self._set_stack(project_dir, "typescript")
        agent = get_phase_agent(feature, "implementing", project_dir, stack=None)
        assert agent == "developer-typescript"


class TestFinalizeBuildCacheWarning:
    """Tests for the low cache hit rate warning in _finalize_build."""

    @patch("devflow.integrations.git.push_and_create_pr", return_value=None)
    def test_warns_when_cache_hit_rate_low(
        self, mock_pr: MagicMock, project_dir: Path,
    ) -> None:
        from devflow.core.history import BuildMetrics, append_build_metrics
        from devflow.core.metrics import PhaseSnapshot
        from devflow.orchestration.build import _finalize_build
        from devflow.orchestration.events import BuildCallbacks
        from devflow.ui.rendering import BuildTotals

        feature = start_build("test", "quick", project_dir)

        # Seed 2 low-cache builds (the 3rd will be appended by _finalize_build).
        for i in range(2):
            record = BuildMetrics(
                feature_id=f"feat-old-{i}", description="old", workflow="quick",
                timestamp=f"2026-04-20T0{i}:00:00+00:00", success=True,
                input_tokens=10000, cache_creation=5000, cache_read=1000,  # ~6.7%
                duration_s=30.0, cost_usd=0.02,
                phases=[PhaseSnapshot(
                    name="implementing", model="sonnet", cost_usd=0.02,
                    input_tokens=10000, cache_creation=5000, cache_read=1000,
                    duration_s=30.0,
                )],
            )
            append_build_metrics(record, project_dir)

        totals = BuildTotals()
        totals.add("implementing", PhaseMetrics(
            input_tokens=10000, cache_creation=5000, cache_read=1000,
            cost_usd=0.02,
        ), 30.0, model="sonnet")

        warnings: list[float] = []
        callbacks = BuildCallbacks(on_low_cache_warning=warnings.append)
        _finalize_build(feature, "feat/test", totals, [], callbacks, project_dir)
        assert warnings, "expected on_low_cache_warning to fire"
        assert warnings[0] < 0.4

    @patch("devflow.integrations.git.push_and_create_pr", return_value=None)
    def test_no_warning_when_cache_hit_rate_ok(
        self, mock_pr: MagicMock, project_dir: Path,
    ) -> None:
        from devflow.core.history import BuildMetrics, append_build_metrics
        from devflow.core.metrics import PhaseSnapshot
        from devflow.orchestration.build import _finalize_build
        from devflow.orchestration.events import BuildCallbacks
        from devflow.ui.rendering import BuildTotals

        feature = start_build("test", "quick", project_dir)

        # Seed 2 high-cache builds.
        for i in range(2):
            record = BuildMetrics(
                feature_id=f"feat-ok-{i}", description="ok", workflow="quick",
                timestamp=f"2026-04-20T0{i}:00:00+00:00", success=True,
                input_tokens=2000, cache_creation=3000, cache_read=15000,  # 75%
                duration_s=30.0, cost_usd=0.02,
                phases=[PhaseSnapshot(
                    name="implementing", model="sonnet", cost_usd=0.02,
                    input_tokens=2000, cache_creation=3000, cache_read=15000,
                    duration_s=30.0,
                )],
            )
            append_build_metrics(record, project_dir)

        totals = BuildTotals()
        totals.add("implementing", PhaseMetrics(
            input_tokens=2000, cache_creation=3000, cache_read=15000,
            cost_usd=0.02,
        ), 30.0, model="sonnet")

        warnings: list[float] = []
        callbacks = BuildCallbacks(on_low_cache_warning=warnings.append)
        _finalize_build(feature, "feat/test", totals, [], callbacks, project_dir)
        assert not warnings


class TestReviewLoop:
    """Tests for the review→fix→review cycle in the execution loop."""

    def test_should_re_review_true_when_budget_remains(
        self, project_dir: Path,
    ) -> None:
        from devflow.orchestration.review import should_re_review

        feature = start_build("test", "standard", project_dir)
        assert feature.find_phase("reviewing") is not None
        assert should_re_review(feature) is True

    def test_should_re_review_false_after_max_cycles(
        self, project_dir: Path,
    ) -> None:
        from devflow.orchestration.review import MAX_REVIEW_CYCLES, should_re_review

        feature = start_build("test", "standard", project_dir)
        feature.metadata.review_cycles = MAX_REVIEW_CYCLES
        assert should_re_review(feature) is False

    def test_should_re_review_false_without_reviewing_phase(
        self, project_dir: Path,
    ) -> None:
        from devflow.orchestration.review import should_re_review

        feature = start_build("test", "quick", project_dir)
        # quick workflow has no reviewing phase.
        assert feature.find_phase("reviewing") is None
        assert should_re_review(feature) is False

    def test_setup_re_review_resets_and_increments(
        self, project_dir: Path,
    ) -> None:
        from devflow.orchestration.review import setup_re_review

        feature = start_build("test", "standard", project_dir)
        # Simulate reviewing done.
        reviewing = feature.find_phase("reviewing")
        reviewing.start()
        reviewing.complete("LGTM")
        save_state(load_state(project_dir), project_dir)

        setup_re_review(feature.id, project_dir)

        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.metadata.review_cycles == 1
        rev = tracked.find_phase("reviewing")
        assert rev.status == PhaseStatus.PENDING

    def test_setup_re_fix_resets_fixing_and_gate(
        self, project_dir: Path,
    ) -> None:
        from devflow.orchestration.review import setup_re_fix

        feature = start_build("test", "standard", project_dir)
        # Simulate fixing + gate done.
        for name in ("planning", "implementing", "reviewing"):
            p = feature.find_phase(name)
            if p:
                p.start()
                p.complete()
        fixing_p = feature.find_phase("fixing")
        if fixing_p is None:
            from devflow.core.models import PhaseRecord
            fixing_p = PhaseRecord(name="fixing")
            gate_idx = next(
                i for i, p in enumerate(feature.phases) if p.name == "gate"
            )
            feature.phases.insert(gate_idx, fixing_p)
        fixing_p.start()
        fixing_p.complete()
        gate_p = feature.find_phase("gate")
        gate_p.start()
        gate_p.complete()
        feature.status = FeatureStatus.GATE
        state = load_state(project_dir)
        state.features[feature.id] = feature
        save_state(state, project_dir)

        setup_re_fix(feature.id, project_dir)

        state = load_state(project_dir)
        tracked = state.get_feature(feature.id)
        assert tracked.find_phase("fixing").status == PhaseStatus.PENDING
        assert tracked.find_phase("gate").status == PhaseStatus.PENDING
        assert tracked.status == FeatureStatus.FIXING


class TestAutoCommitAfterPhase:
    # Stub porcelain so the build loop *thinks* the agent left dirty changes
    # — required since the auto-commit guard short-circuits when the working
    # tree is clean (the unit test runs in tmp_path with no real git repo).
    @patch("devflow.orchestration.build.git_status_porcelain", return_value=" M f")
    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_diff_stat", return_value="")
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_OK)
    @patch("devflow.integrations.git.create_branch", return_value="feat/test")
    @patch("devflow.integrations.git.push_and_create_pr", return_value="https://github.com/pr/1")
    def test_commit_called_after_implementing(
        self, mock_pr: MagicMock, mock_branch: MagicMock,
        mock_exec: MagicMock, mock_diff: MagicMock, mock_commit: MagicMock,
        mock_porcelain: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_build("test", "quick", project_dir)
        execute_build_loop(feature, base=project_dir)
        commit_msgs = [c[0][0] for c in mock_commit.call_args_list]
        assert any("implementing" in msg for msg in commit_msgs), (
            f"expected an 'implementing' commit, got {commit_msgs!r}"
        )

    @patch("devflow.orchestration.build.git_status_porcelain", return_value=" M f")
    @patch("devflow.integrations.git.commit_changes", return_value=False)
    @patch("devflow.integrations.git.get_diff_stat", return_value="")
    @patch("devflow.orchestration.build._execute_phase", return_value=_PHASE_OK)
    @patch("devflow.integrations.git.create_branch", return_value="feat/test")
    @patch("devflow.integrations.git.push_and_create_pr", return_value="https://github.com/pr/1")
    def test_commit_not_called_for_gate(
        self, mock_pr: MagicMock, mock_branch: MagicMock,
        mock_exec: MagicMock, mock_diff: MagicMock, mock_commit: MagicMock,
        mock_porcelain: MagicMock,
        project_dir: Path,
    ) -> None:
        feature = start_build("test", "quick", project_dir)
        execute_build_loop(feature, base=project_dir)
        commit_msgs = [c[0][0] for c in mock_commit.call_args_list]
        assert not any("gate" in msg for msg in commit_msgs)
