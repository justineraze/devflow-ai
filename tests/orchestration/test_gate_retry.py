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
from devflow.orchestration.build import (
    MAX_GATE_AUTO_RETRIES,
    _setup_gate_retry,
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

        scheduled = _setup_gate_retry("feat-001", project_dir)

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
        assert feature.metadata["gate_retry"] == 1
        assert feature.status == FeatureStatus.FIXING

    def test_resets_existing_fixing_phase(self, project_dir: Path) -> None:
        _make_feature_with_gate(project_dir, with_fixing=True)

        _setup_gate_retry("feat-001", project_dir)

        from devflow.core.workflow import load_state
        feature = load_state(project_dir).get_feature("feat-001")
        names = [p.name for p in feature.phases]
        assert names.count("fixing") == 1
        fixing = next(p for p in feature.phases if p.name == "fixing")
        assert fixing.status == PhaseStatus.PENDING
        assert fixing.output == ""

    def test_refuses_second_retry(self, project_dir: Path) -> None:
        feature = _make_feature_with_gate(project_dir, with_fixing=False)
        feature.metadata["gate_retry"] = MAX_GATE_AUTO_RETRIES
        state = WorkflowState(features={feature.id: feature})
        save_state(state, project_dir)

        scheduled = _setup_gate_retry("feat-001", project_dir)

        assert scheduled is False

    def test_returns_false_for_unknown_feature(self, project_dir: Path) -> None:
        assert _setup_gate_retry("ghost", project_dir) is False


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
