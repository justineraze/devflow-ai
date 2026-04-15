"""Tests for artifact-aware model routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devflow.core.artifacts import write_artifact
from devflow.core.models import Feature, FeatureStatus, PhaseRecord
from devflow.core.phases import get_spec
from devflow.orchestration.model_routing import SMALL_DIFF_THRESHOLD, resolve_model


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_feature() -> Feature:
    return Feature(
        id="feat-001",
        description="test",
        status=FeatureStatus.PENDING,
        phases=[],
    )


class TestResolutionOrder:
    def test_yaml_override_wins(self, project_dir: Path) -> None:
        feature = _make_feature()
        phase = PhaseRecord(name="reviewing", model="haiku")
        assert resolve_model(feature, phase) == "haiku"

    def test_default_when_no_override_and_no_artifact(self, project_dir: Path) -> None:
        feature = _make_feature()
        phase = PhaseRecord(name="architecture")
        assert resolve_model(feature, phase) == get_spec("architecture").model_default

    def test_unknown_phase_name_is_rejected_at_construction(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PhaseRecord(name="unknown")


class TestFixingSelector:
    def _write_gate(self, feature_id: str, project_dir: Path, checks: list[dict]) -> None:
        write_artifact(
            feature_id,
            "gate.json",
            json.dumps({"passed": all(c["passed"] for c in checks), "checks": checks}),
            project_dir,
        )

    def test_haiku_when_only_ruff_fails(self, project_dir: Path) -> None:
        self._write_gate("feat-001", project_dir, [
            {"name": "ruff", "passed": False, "message": "E501"},
            {"name": "pytest", "passed": True, "message": "ok"},
            {"name": "secrets", "passed": True, "message": "ok"},
        ])
        feature = _make_feature()
        phase = PhaseRecord(name="fixing")
        assert resolve_model(feature, phase) == "haiku"

    def test_sonnet_when_pytest_fails(self, project_dir: Path) -> None:
        self._write_gate("feat-001", project_dir, [
            {"name": "ruff", "passed": False, "message": "E501"},
            {"name": "pytest", "passed": False, "message": "2 failed"},
        ])
        feature = _make_feature()
        phase = PhaseRecord(name="fixing")
        assert resolve_model(feature, phase) == get_spec("fixing").model_default

    def test_sonnet_when_no_gate_artifact(self, project_dir: Path) -> None:
        feature = _make_feature()
        phase = PhaseRecord(name="fixing")
        assert resolve_model(feature, phase) == get_spec("fixing").model_default

    def test_sonnet_when_no_failing_checks(self, project_dir: Path) -> None:
        self._write_gate("feat-001", project_dir, [
            {"name": "ruff", "passed": True, "message": "ok"},
        ])
        feature = _make_feature()
        phase = PhaseRecord(name="fixing")
        assert resolve_model(feature, phase) == get_spec("fixing").model_default


class TestReviewingSelector:
    def _write_files(self, feature_id: str, project_dir: Path, data: dict) -> None:
        write_artifact(feature_id, "files.json", json.dumps(data), project_dir)

    def test_sonnet_for_small_non_critical_diff(self, project_dir: Path) -> None:
        self._write_files("feat-001", project_dir, {
            "lines_added": 20,
            "lines_removed": 5,
            "files_changed": 2,
            "paths": ["src/foo.py", "tests/test_foo.py"],
            "critical_paths": [],
        })
        feature = _make_feature()
        phase = PhaseRecord(name="reviewing")
        assert resolve_model(feature, phase) == "sonnet"

    def test_opus_for_large_diff(self, project_dir: Path) -> None:
        self._write_files("feat-001", project_dir, {
            "lines_added": SMALL_DIFF_THRESHOLD + 10,
            "lines_removed": 0,
            "files_changed": 3,
            "paths": ["src/foo.py"],
            "critical_paths": [],
        })
        feature = _make_feature()
        phase = PhaseRecord(name="reviewing")
        assert resolve_model(feature, phase) == "opus"

    def test_opus_when_critical_path_touched(self, project_dir: Path) -> None:
        self._write_files("feat-001", project_dir, {
            "lines_added": 10,
            "lines_removed": 2,
            "files_changed": 1,
            "paths": ["src/auth/login.py"],
            "critical_paths": ["src/auth/login.py"],
        })
        feature = _make_feature()
        phase = PhaseRecord(name="reviewing")
        assert resolve_model(feature, phase) == "opus"

    def test_opus_when_no_files_artifact(self, project_dir: Path) -> None:
        feature = _make_feature()
        phase = PhaseRecord(name="reviewing")
        assert resolve_model(feature, phase) == "opus"


class TestYamlOverride:
    def test_override_beats_selector(self, project_dir: Path) -> None:
        write_artifact("feat-001", "gate.json", json.dumps({
            "passed": False,
            "checks": [{"name": "ruff", "passed": False, "message": "E501"}],
        }), project_dir)
        feature = _make_feature()
        phase = PhaseRecord(name="fixing", model="opus")
        assert resolve_model(feature, phase) == "opus"
