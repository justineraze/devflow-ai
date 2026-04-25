"""Tests for devflow.core.history — build metrics persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.history import (
    BuildMetrics,
    PhaseSnapshot,
    append_build_metrics,
    build_metrics_from,
    read_history,
)
from devflow.core.models import (
    Feature,
    FeatureStatus,
    PhaseRecord,
    PhaseStatus,
)


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestBuildMetrics:
    def test_cache_hit_rate_with_cache(self) -> None:
        r = BuildMetrics(
            feature_id="f-1", description="test", workflow="standard",
            timestamp="2026-01-01T00:00:00Z",
            input_tokens=200, cache_creation=800, cache_read=1000,
        )
        # 1000 / (200 + 800 + 1000) = 0.5
        assert r.cache_hit_rate == pytest.approx(0.5)

    def test_cache_hit_rate_zero_tokens(self) -> None:
        r = BuildMetrics(
            feature_id="f-1", description="test", workflow="standard",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert r.cache_hit_rate == 0.0

    def test_cache_hit_rate_no_cache(self) -> None:
        r = BuildMetrics(
            feature_id="f-1", description="test", workflow="quick",
            timestamp="2026-01-01T00:00:00Z",
            input_tokens=5000, cache_creation=40000, cache_read=0,
        )
        assert r.cache_hit_rate == 0.0

    def test_phase_costs_property(self) -> None:
        r = BuildMetrics(
            feature_id="f-1", description="test", workflow="standard",
            timestamp="t",
            phases=[
                PhaseSnapshot(name="planning", cost_usd=0.30, model="sonnet"),
                PhaseSnapshot(name="implementing", cost_usd=1.20, model="sonnet"),
            ],
        )
        assert r.phase_costs == {"planning": 0.30, "implementing": 1.20}

    def test_phase_durations_property(self) -> None:
        r = BuildMetrics(
            feature_id="f-1", description="test", workflow="standard",
            timestamp="t",
            phases=[
                PhaseSnapshot(name="planning", duration_s=60.0),
                PhaseSnapshot(name="implementing", duration_s=300.0),
            ],
        )
        assert r.phase_durations == {"planning": 60.0, "implementing": 300.0}


class TestAppendAndRead:
    def test_roundtrip_with_phases(self, project_dir: Path) -> None:
        record = BuildMetrics(
            feature_id="feat-test-001",
            description="Add caching",
            workflow="standard",
            timestamp="2026-04-20T10:00:00Z",
            success=True,
            duration_s=645.0,
            cost_usd=1.95,
            input_tokens=500,
            output_tokens=22000,
            cache_creation=45000,
            cache_read=280000,
            tool_count=81,
            gate_passed_first_try=True,
            gate_retries=0,
            phases_total=4,
            phases_completed=4,
            phases=[
                PhaseSnapshot(
                    name="planning", model="sonnet", cost_usd=0.30,
                    input_tokens=100, cache_read=50000, duration_s=72.0,
                ),
                PhaseSnapshot(
                    name="implementing", model="sonnet", cost_usd=1.20,
                    input_tokens=300, cache_read=180000, duration_s=400.0,
                    tool_count=60,
                ),
            ],
        )
        append_build_metrics(record, project_dir)

        history = read_history(project_dir)
        assert len(history) == 1
        r = history[0]
        assert r.feature_id == "feat-test-001"
        assert r.success is True
        assert r.cost_usd == 1.95
        assert len(r.phases) == 2
        assert r.phases[0].name == "planning"
        assert r.phases[0].model == "sonnet"
        assert r.phases[1].cost_usd == 1.20

    def test_failed_build_record(self, project_dir: Path) -> None:
        record = BuildMetrics(
            feature_id="feat-fail",
            description="Broken feature",
            workflow="standard",
            timestamp="2026-04-20T11:00:00Z",
            success=False,
            failed_phase="implementing",
            cost_usd=0.50,
            phases=[
                PhaseSnapshot(name="planning", model="sonnet", success=True),
                PhaseSnapshot(name="implementing", model="sonnet", success=False),
            ],
        )
        append_build_metrics(record, project_dir)

        history = read_history(project_dir)
        assert len(history) == 1
        assert history[0].success is False
        assert history[0].failed_phase == "implementing"
        assert history[0].phases[1].success is False

    def test_multiple_appends_ordered_most_recent_first(
        self, project_dir: Path,
    ) -> None:
        for i in range(3):
            append_build_metrics(BuildMetrics(
                feature_id=f"feat-{i}",
                description=f"Feature {i}",
                workflow="quick",
                timestamp=f"2026-04-{20 + i}T10:00:00Z",
                cost_usd=float(i),
            ), project_dir)

        history = read_history(project_dir)
        assert len(history) == 3
        assert history[0].feature_id == "feat-2"
        assert history[2].feature_id == "feat-0"

    def test_limit_parameter(self, project_dir: Path) -> None:
        for i in range(10):
            append_build_metrics(BuildMetrics(
                feature_id=f"feat-{i}", description="x", workflow="quick",
                timestamp=f"2026-04-{i:02d}T00:00:00Z",
            ), project_dir)

        history = read_history(project_dir, limit=3)
        assert len(history) == 3
        assert history[0].feature_id == "feat-9"

    def test_empty_history(self, project_dir: Path) -> None:
        assert read_history(project_dir) == []

    def test_corrupt_lines_skipped(self, project_dir: Path) -> None:
        metrics_path = project_dir / ".devflow" / "metrics.jsonl"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(
            '{"feature_id":"f-1","description":"ok","workflow":"q",'
            '"timestamp":"t","success":true}\n'
            "not json\n"
            '{"feature_id":"f-2","description":"ok","workflow":"q",'
            '"timestamp":"t","success":true}\n'
        )

        history = read_history(project_dir)
        assert len(history) == 2


class TestBuildMetricsFrom:
    def test_successful_build(self, project_dir: Path) -> None:
        from devflow.core.metrics import BuildTotals, PhaseSnapshot

        feature = Feature(
            id="feat-test",
            description="Add metrics tracking",
            workflow="standard",
            status=FeatureStatus.DONE,
            phases=[
                PhaseRecord(name="planning", status=PhaseStatus.DONE),
                PhaseRecord(name="implementing", status=PhaseStatus.DONE),
                PhaseRecord(name="reviewing", status=PhaseStatus.DONE),
                PhaseRecord(name="gate", status=PhaseStatus.DONE),
            ],
        )

        totals = BuildTotals()
        totals.cost_usd = 1.50
        totals.input_tokens = 300
        totals.output_tokens = 15000
        totals.cache_creation = 45000
        totals.cache_read = 250000
        totals.tool_count = 60
        totals.duration_s = 500.0
        totals.phase_snapshots = [
            PhaseSnapshot(
                name="planning", model="sonnet", cost_usd=0.30,
                input_tokens=100, output_tokens=5000, cache_creation=40000,
                cache_read=80000, tool_count=20, duration_s=100.0, success=True,
            ),
            PhaseSnapshot(
                name="implementing", model="sonnet", cost_usd=1.20,
                input_tokens=200, output_tokens=10000, cache_creation=5000,
                cache_read=170000, tool_count=40, duration_s=400.0, success=True,
            ),
        ]

        record = build_metrics_from(feature, totals, success=True)

        assert record.feature_id == "feat-test"
        assert record.success is True
        assert record.failed_phase is None
        assert record.cost_usd == 1.50
        assert record.phases_total == 4
        assert record.phases_completed == 4
        assert record.gate_passed_first_try is True
        assert len(record.phases) == 2
        assert record.phases[0].model == "sonnet"
        assert record.phases[1].cost_usd == 1.20

    def test_failed_build(self, project_dir: Path) -> None:
        from devflow.core.metrics import BuildTotals, PhaseSnapshot

        feature = Feature(
            id="feat-fail",
            description="Test",
            workflow="standard",
            status=FeatureStatus.FAILED,
            phases=[
                PhaseRecord(name="planning", status=PhaseStatus.DONE),
                PhaseRecord(name="implementing", status=PhaseStatus.FAILED),
            ],
        )

        totals = BuildTotals()
        totals.phase_snapshots = [
            PhaseSnapshot(
                name="planning", model="sonnet", cost_usd=0.30,
                input_tokens=100, output_tokens=5000, cache_creation=40000,
                cache_read=80000, tool_count=20, duration_s=100.0, success=True,
            ),
            PhaseSnapshot(
                name="implementing", model="sonnet", cost_usd=0.50,
                input_tokens=200, output_tokens=3000, cache_creation=5000,
                cache_read=90000, tool_count=15, duration_s=200.0, success=False,
            ),
        ]

        record = build_metrics_from(feature, totals, success=False)

        assert record.success is False
        assert record.failed_phase == "implementing"
        assert record.gate_passed_first_try is False
        assert record.phases_completed == 1

    def test_gate_retry_tracked(self, project_dir: Path) -> None:
        from devflow.ui.rendering import BuildTotals

        feature = Feature(
            id="feat-retry",
            description="Test",
            workflow="standard",
            status=FeatureStatus.DONE,
            phases=[
                PhaseRecord(name="implementing", status=PhaseStatus.DONE),
                PhaseRecord(name="gate", status=PhaseStatus.DONE),
            ],
        )
        feature.metadata.gate_retry = 1

        totals = BuildTotals()
        record = build_metrics_from(feature, totals, success=True)

        assert record.gate_passed_first_try is False
        assert record.gate_retries == 1
