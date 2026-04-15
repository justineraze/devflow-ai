"""Tests for per-feature artifact storage and selective context injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.artifacts import (
    artifact_path,
    context_deps_for,
    feature_dir,
    load_phase_output,
    read_artifact,
    save_phase_output,
    write_artifact,
)
from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseRecord,
    PhaseStatus,
)
from devflow.orchestration.runner import _build_phase_context


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated project dir where .devflow/ lives."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestArtifactIO:
    def test_feature_dir_is_created(self, project_dir: Path) -> None:
        path = feature_dir("feat-001")
        assert path.exists()
        assert path == project_dir / ".devflow" / "feat-001"

    def test_write_and_read_roundtrip(self, project_dir: Path) -> None:
        write_artifact("feat-001", "plan.md", "# Plan\n\nStep 1")
        assert read_artifact("feat-001", "plan.md") == "# Plan\n\nStep 1"

    def test_read_missing_returns_none(self, project_dir: Path) -> None:
        assert read_artifact("feat-001", "missing.md") is None

    def test_write_is_atomic(self, project_dir: Path) -> None:
        """Tmp file must not remain after successful write."""
        write_artifact("feat-001", "plan.md", "content")
        tmp = artifact_path("feat-001", "plan.md.tmp")
        assert not tmp.exists()

    def test_save_and_load_phase_output(self, project_dir: Path) -> None:
        save_phase_output("feat-001", "planning", "# Plan body")
        assert load_phase_output("feat-001", "planning") == "# Plan body"


class TestContextDeps:
    def test_architecture_has_no_deps(self) -> None:
        assert context_deps_for("architecture") == ()

    def test_planning_depends_on_architecture(self) -> None:
        assert context_deps_for("planning") == ("architecture",)

    def test_fixing_depends_only_on_reviewing(self) -> None:
        """Fixing should NOT re-pull planning or architecture."""
        assert context_deps_for("fixing") == ("reviewing",)

    def test_reviewing_depends_on_planning_not_architecture(self) -> None:
        """Reviewing already has the diff — only needs the plan as rubric."""
        assert context_deps_for("reviewing") == ("planning",)

    def test_gate_has_no_deps(self) -> None:
        assert context_deps_for("gate") == ()

    def test_unknown_phase_defaults_to_empty(self) -> None:
        assert context_deps_for("nonexistent") == ()


class TestSelectiveInjection:
    """_build_phase_context must only include the declared dependencies."""

    def _make_feature(self, phases: list[tuple[str, str]]) -> Feature:
        """Build a Feature with DONE phases — artifacts written to cwd/.devflow/."""
        records = []
        for name, output in phases:
            record = PhaseRecord(name=name, status=PhaseStatus.DONE)
            records.append(record)
            if output:
                save_phase_output("feat-001", name, output)
        return Feature(
            id="feat-001",
            description="test",
            status=FeatureStatus.IMPLEMENTING,
            phases=records,
        )

    def test_fixing_pulls_only_reviewing(self, project_dir: Path) -> None:
        feature = self._make_feature([
            ("architecture", "ARCH OUTPUT"),
            ("planning", "PLAN OUTPUT"),
            ("implementing", "IMPL OUTPUT"),
            ("reviewing", "REVIEW OUTPUT"),
        ])
        phase = PhaseRecord(name="fixing")

        ctx = _build_phase_context(feature, phase)

        assert "REVIEW OUTPUT" in ctx
        assert "ARCH OUTPUT" not in ctx
        assert "PLAN OUTPUT" not in ctx
        assert "IMPL OUTPUT" not in ctx

    def test_architecture_has_empty_context(self, project_dir: Path) -> None:
        feature = self._make_feature([])
        phase = PhaseRecord(name="architecture")
        assert _build_phase_context(feature, phase) == ""

    def test_prefers_on_disk_artifact_over_memory(
        self, project_dir: Path,
    ) -> None:
        """Artifacts on disk win — they are the canonical, fresh version."""
        feature = self._make_feature([
            ("architecture", "ARCH"),
            ("planning", "MEMORY PLAN"),
        ])
        # Overwrite with a fresher version — this is what the reader should see.
        save_phase_output("feat-001", "planning", "DISK PLAN")
        phase = PhaseRecord(name="reviewing")

        ctx = _build_phase_context(feature, phase)

        assert "DISK PLAN" in ctx
        assert "MEMORY PLAN" not in ctx

    def test_empty_context_when_artifact_missing(
        self, project_dir: Path,
    ) -> None:
        """No artifact on disk → empty context. In-memory output is not a fallback."""
        records = [PhaseRecord(name="planning", status=PhaseStatus.DONE)]
        feature = Feature(
            id="feat-001", description="test",
            status=FeatureStatus.IMPLEMENTING, phases=records,
        )
        phase = PhaseRecord(name="reviewing")

        ctx = _build_phase_context(feature, phase)

        assert ctx == ""
