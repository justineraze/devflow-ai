"""Tests for the gate→fixing→gate auto-retry loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.artifacts import read_artifact, write_artifact
from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseRecord,
    PhaseStatus,
    WorkflowState,
)
from devflow.core.workflow import save_state
from devflow.orchestration.phase_exec import (
    MAX_GATE_AUTO_RETRIES,
    setup_gate_retry,
)
from devflow.orchestration.runner import build_user_prompt


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_feature_with_gate(project_dir: Path, with_fixing: bool) -> Feature:
    phases = [
        PhaseRecord(name="planning", status=PhaseStatus.DONE),
        PhaseRecord(name="implementing", status=PhaseStatus.DONE),
        PhaseRecord(name="reviewing", status=PhaseStatus.DONE),
    ]
    if with_fixing:
        phases.append(PhaseRecord(name="fixing", status=PhaseStatus.DONE))
    phases.append(PhaseRecord(name="gate", status=PhaseStatus.DONE))

    feature = Feature(
        id="feat-001",
        description="test",
        status=FeatureStatus.GATE,
        phases=phases,
    )
    state = WorkflowState(features={feature.id: feature})
    save_state(state, project_dir)
    return feature


class TestSetupGateRetry:
    def test_schedules_retry_and_injects_fixing_phase(
        self, project_dir: Path,
    ) -> None:
        _make_feature_with_gate(project_dir, with_fixing=False)

        scheduled = setup_gate_retry("feat-001", project_dir)

        assert scheduled is True
        from devflow.core.workflow import load_state
        feature = load_state(project_dir).get_feature("feat-001")
        phase_names = [p.name for p in feature.phases]
        assert "fixing" in phase_names
        assert phase_names.index("fixing") < phase_names.index("gate")
        fixing = next(p for p in feature.phases if p.name == "fixing")
        gate = next(p for p in feature.phases if p.name == "gate")
        assert fixing.status == PhaseStatus.PENDING
        assert gate.status == PhaseStatus.PENDING
        assert feature.metadata.gate_retry == 1
        assert feature.status == FeatureStatus.FIXING

    def test_resets_existing_fixing_phase(self, project_dir: Path) -> None:
        _make_feature_with_gate(project_dir, with_fixing=True)

        setup_gate_retry("feat-001", project_dir)

        from devflow.core.workflow import load_state
        feature = load_state(project_dir).get_feature("feat-001")
        names = [p.name for p in feature.phases]
        assert names.count("fixing") == 1
        fixing = next(p for p in feature.phases if p.name == "fixing")
        assert fixing.status == PhaseStatus.PENDING
        assert fixing.output == ""

    def test_allows_three_retries(self, project_dir: Path) -> None:
        """MAX_GATE_AUTO_RETRIES is now 3 — three successive retries succeed."""
        _make_feature_with_gate(project_dir, with_fixing=True)

        from devflow.core.workflow import load_state

        for attempt in range(1, 4):
            assert setup_gate_retry("feat-001", project_dir) is True
            feature = load_state(project_dir).get_feature("feat-001")
            assert feature.metadata.gate_retry == attempt

        # Fourth attempt should be refused.
        assert setup_gate_retry("feat-001", project_dir) is False

    def test_refuses_after_max_retries(self, project_dir: Path) -> None:
        feature = _make_feature_with_gate(project_dir, with_fixing=False)
        feature.metadata.gate_retry = MAX_GATE_AUTO_RETRIES
        state = WorkflowState(features={feature.id: feature})
        save_state(state, project_dir)

        scheduled = setup_gate_retry("feat-001", project_dir)

        assert scheduled is False

    def test_gate_retry_models_tracks_escalation(self, project_dir: Path) -> None:
        """gate_retry_models records the tier for each retry."""
        _make_feature_with_gate(project_dir, with_fixing=True)

        from devflow.core.workflow import load_state

        setup_gate_retry("feat-001", project_dir)
        feature = load_state(project_dir).get_feature("feat-001")
        # Retry 1: no escalation (None = use selector).
        assert feature.metadata.gate_retry_models == [None]

        # Reset gate to DONE so we can retry again.
        gate = feature.find_phase("gate")
        gate.status = PhaseStatus.DONE
        save_state(WorkflowState(features={feature.id: feature}), project_dir)

        setup_gate_retry("feat-001", project_dir)
        feature = load_state(project_dir).get_feature("feat-001")
        # Retry 2: escalate to STANDARD (canonical tier).
        assert feature.metadata.gate_retry_models == [None, "standard"]

        gate = feature.find_phase("gate")
        gate.status = PhaseStatus.DONE
        save_state(WorkflowState(features={feature.id: feature}), project_dir)

        setup_gate_retry("feat-001", project_dir)
        feature = load_state(project_dir).get_feature("feat-001")
        # Retry 3: escalate to THINKING.
        assert feature.metadata.gate_retry_models == [None, "standard", "thinking"]

    def test_returns_false_for_unknown_feature(self, project_dir: Path) -> None:
        assert setup_gate_retry("ghost", project_dir) is False


class TestFixingPromptInjectsGateJson:
    def test_gate_json_present_in_prompt(self, project_dir: Path) -> None:
        write_artifact(
            "feat-001",
            "gate.json",
            '{"passed": false, "checks": [{"name": "ruff"}]}',
            project_dir,
        )
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.FIXING,
            phases=[PhaseRecord(name="fixing", status=PhaseStatus.IN_PROGRESS)],
        )

        prompt = build_user_prompt(feature, feature.phases[0])

        assert "Gate failures to fix" in prompt
        assert '"name": "ruff"' in prompt

    def test_no_gate_section_when_artifact_missing(
        self, project_dir: Path,
    ) -> None:
        assert read_artifact("feat-001", "gate.json") is None
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.FIXING,
            phases=[PhaseRecord(name="fixing", status=PhaseStatus.IN_PROGRESS)],
        )

        prompt = build_user_prompt(feature, feature.phases[0])

        assert "Gate failures to fix" not in prompt


class TestRetryContextInPrompt:
    def test_retry_context_injected_when_gate_retry_positive(
        self, project_dir: Path,
    ) -> None:
        write_artifact(
            "feat-001",
            "gate.json",
            '{"passed": false, "checks": [{"name": "pytest", "passed": false}]}',
            project_dir,
        )
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.FIXING,
            phases=[PhaseRecord(name="fixing", status=PhaseStatus.IN_PROGRESS)],
        )
        feature.metadata.gate_retry = 1

        prompt = build_user_prompt(feature, feature.phases[0])

        assert "Tentatives précédentes" in prompt
        assert "approche différente" in prompt

    def test_no_retry_context_on_first_fixing(
        self, project_dir: Path,
    ) -> None:
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.FIXING,
            phases=[PhaseRecord(name="fixing", status=PhaseStatus.IN_PROGRESS)],
        )
        # gate_retry == 0 by default

        prompt = build_user_prompt(feature, feature.phases[0])

        assert "Tentatives précédentes" not in prompt

    def test_retry_context_includes_gate_errors_on_latest(
        self, project_dir: Path,
    ) -> None:
        write_artifact(
            "feat-001",
            "gate.json",
            '{"passed": false, "checks": [{"name": "pytest", "passed": false}]}',
            project_dir,
        )
        feature = Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.FIXING,
            phases=[PhaseRecord(name="fixing", status=PhaseStatus.IN_PROGRESS)],
        )
        feature.metadata.gate_retry = 2

        prompt = build_user_prompt(feature, feature.phases[0])

        assert "Tentatives précédentes (2)" in prompt
        # Gate errors only on the latest attempt.
        assert "Erreur gate" in prompt
