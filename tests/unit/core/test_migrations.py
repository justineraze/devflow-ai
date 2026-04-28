"""Tests for devflow.core.migrations — schema migration helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from devflow.core.migrations import (
    CONFIG_VERSION,
    METRICS_VERSION,
    STATE_VERSION,
    migrate_config,
    migrate_metrics_line,
    migrate_state,
)


class TestMigrateState:
    def test_v1_to_v1_is_noop(self) -> None:
        data = {"version": 1, "features": {}}
        result = migrate_state(data, 1, 1)
        assert result == {"version": 1, "features": {}}

    def test_missing_version_treated_as_v1(self) -> None:
        data = {"features": {"feat-1": {}}}
        result = migrate_state(data, 1, STATE_VERSION)
        assert result["features"] == {"feat-1": {}}

    def test_idempotent(self) -> None:
        data = {"version": 1, "features": {}}
        first = migrate_state(dict(data), 1, STATE_VERSION)
        second = migrate_state(dict(first), 1, STATE_VERSION)
        assert first == second

    @pytest.mark.skip(reason="No v2 migration yet — placeholder for future")
    def test_v1_to_v2(self) -> None:
        data = {"version": 1, "features": {}}
        result = migrate_state(data, 1, 2)
        assert result["version"] == 2


class TestMigrateConfig:
    def test_v1_to_v1_is_noop(self) -> None:
        data = {"version": 1, "stack": "python"}
        result = migrate_config(data, 1, 1)
        assert result == {"version": 1, "stack": "python"}

    def test_missing_version_treated_as_v1(self) -> None:
        data = {"stack": "python"}
        result = migrate_config(data, 1, CONFIG_VERSION)
        assert result["stack"] == "python"

    def test_idempotent(self) -> None:
        data = {"version": 1, "stack": "python"}
        first = migrate_config(dict(data), 1, CONFIG_VERSION)
        second = migrate_config(dict(first), 1, CONFIG_VERSION)
        assert first == second

    @pytest.mark.skip(reason="No v2 migration yet — placeholder for future")
    def test_v1_to_v2(self) -> None:
        data = {"version": 1, "stack": "python"}
        result = migrate_config(data, 1, 2)
        assert result["version"] == 2


class TestMigrateMetricsLine:
    def test_v2_to_v2_is_passthrough(self) -> None:
        data = {
            "version": 2, "feature_id": "f1", "phase": "implementing",
            "backend": "claude", "outcome": "success",
        }
        result = migrate_metrics_line(data, 2, 2)
        assert result == [data]

    def test_v1_to_v2_single_phase(self) -> None:
        data = {
            "version": 1, "feature_id": "f1", "description": "test",
            "workflow": "quick", "success": True,
            "timestamp": "2026-04-20T10:00:00+00:00",
            "duration_s": 120.0, "cost_usd": 0.50,
            "input_tokens": 1000, "output_tokens": 500,
            "cache_read": 200, "cache_creation": 100,
            "phases": [
                {
                    "name": "implementing", "model": "sonnet",
                    "cost_usd": 0.50, "duration_s": 120.0,
                    "input_tokens": 1000, "output_tokens": 500,
                    "cache_read": 200, "cache_creation": 100,
                    "success": True,
                },
            ],
        }
        result = migrate_metrics_line(data, 1, 2)
        assert len(result) == 1
        r = result[0]
        assert r["version"] == 2
        assert r["feature_id"] == "f1"
        assert r["phase"] == "implementing"
        assert r["backend"] == "claude"
        assert r["cost_usd"] == 0.50
        assert r["model"] == "sonnet"
        assert r["outcome"] == "success"
        assert r["tokens"]["in"] == 1000
        assert r["tokens"]["cache_read"] == 200

    def test_v1_to_v2_multi_phase(self) -> None:
        data = {
            "version": 1, "feature_id": "f2", "description": "multi",
            "workflow": "standard", "success": True,
            "timestamp": "2026-04-20T10:00:00+00:00",
            "phases": [
                {"name": "planning", "model": "sonnet", "cost_usd": 0.10,
                 "duration_s": 60.0, "success": True,
                 "input_tokens": 100, "output_tokens": 50,
                 "cache_read": 30, "cache_creation": 10},
                {"name": "implementing", "model": "sonnet", "cost_usd": 0.30,
                 "duration_s": 180.0, "success": True,
                 "input_tokens": 500, "output_tokens": 200,
                 "cache_read": 100, "cache_creation": 50},
                {"name": "gate", "model": "haiku", "cost_usd": 0.05,
                 "duration_s": 30.0, "success": True,
                 "input_tokens": 50, "output_tokens": 10,
                 "cache_read": 5, "cache_creation": 0},
            ],
        }
        result = migrate_metrics_line(data, 1, 2)
        assert len(result) == 3
        assert result[0]["phase"] == "planning"
        assert result[1]["phase"] == "implementing"
        assert result[2]["phase"] == "gate"
        for r in result:
            assert r["version"] == 2
            assert r["backend"] == "claude"

    def test_v1_no_phases_produces_single_record(self) -> None:
        data = {
            "version": 1, "feature_id": "f3", "description": "no phases",
            "workflow": "quick", "success": False,
            "timestamp": "2026-04-20T10:00:00+00:00",
            "duration_s": 60.0, "cost_usd": 0.10,
        }
        result = migrate_metrics_line(data, 1, 2)
        assert len(result) == 1
        assert result[0]["outcome"] == "failure"


class TestVersionConstants:
    def test_current_versions(self) -> None:
        assert STATE_VERSION == 1
        assert CONFIG_VERSION == 1
        assert METRICS_VERSION == 2


# ── Round-trip integration tests ────────────────────────────────────


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".devflow").mkdir()
    return tmp_path


class TestStateVersionRoundTrip:
    def test_load_state_adds_version_when_missing(self, project_dir: Path) -> None:
        from devflow.core.workflow import load_state

        state_file = project_dir / ".devflow" / "state.json"
        state_file.write_text(json.dumps({"features": {}}))
        state = load_state(project_dir)
        assert state.version == 1

    def test_load_state_preserves_version(self, project_dir: Path) -> None:
        from devflow.core.workflow import load_state

        state_file = project_dir / ".devflow" / "state.json"
        state_file.write_text(json.dumps({"version": 1, "features": {}}))
        state = load_state(project_dir)
        assert state.version == 1


class TestConfigVersionRoundTrip:
    def test_load_config_adds_version_when_missing(self, project_dir: Path) -> None:
        from devflow.core.config import clear_config_cache, load_config

        config_file = project_dir / ".devflow" / "config.yaml"
        config_file.write_text(yaml.dump({"stack": "python"}))
        clear_config_cache()
        config = load_config(project_dir)
        assert config.version == 1

    def test_save_config_includes_version(self, project_dir: Path) -> None:
        from devflow.core.config import DevflowConfig, save_config

        save_config(DevflowConfig(stack="python"), project_dir)
        raw = yaml.safe_load((project_dir / ".devflow" / "config.yaml").read_text())
        assert raw["version"] == 1


class TestMetricsVersionRoundTrip:
    def test_read_history_v1_records(self, project_dir: Path) -> None:
        """v1 records without 'phase' key are parsed as v1 BuildMetrics."""
        from devflow.core.history import read_history

        metrics_file = project_dir / ".devflow" / "metrics.jsonl"
        record = {
            "feature_id": "f1", "description": "test", "workflow": "quick",
            "timestamp": "2026-01-01T00:00:00Z", "success": True,
        }
        metrics_file.write_text(json.dumps(record) + "\n")
        history = read_history(project_dir)
        assert len(history) == 1

    def test_read_phase_records_v2(self, project_dir: Path) -> None:
        """v2 flat records are read as MetricsRecord."""
        from devflow.core.history import read_phase_records

        metrics_file = project_dir / ".devflow" / "metrics.jsonl"
        record = {
            "version": 2, "feature_id": "f1", "description": "test",
            "workflow": "quick", "phase": "implementing", "backend": "claude",
            "ts_start": "2026-04-20T10:00:00Z", "ts_end": "2026-04-20T10:05:00Z",
            "duration_s": 300.0, "cost_usd": 0.50,
            "tokens": {"in": 1000, "out": 500, "cache_read": 200, "cache_creation": 100},
            "model": "sonnet", "outcome": "success",
        }
        metrics_file.write_text(json.dumps(record) + "\n")
        records = read_phase_records(project_dir)
        assert len(records) == 1
        assert records[0].feature_id == "f1"
        assert records[0].phase == "implementing"
        assert records[0].tokens_in == 1000

    def test_read_phase_records_migrates_v1(self, project_dir: Path) -> None:
        """v1 records with phases are migrated to multiple v2 records."""
        from devflow.core.history import read_phase_records

        metrics_file = project_dir / ".devflow" / "metrics.jsonl"
        record = {
            "version": 1, "feature_id": "f1", "description": "test",
            "workflow": "standard", "success": True,
            "timestamp": "2026-04-20T10:00:00+00:00",
            "phases": [
                {"name": "planning", "model": "sonnet", "cost_usd": 0.10,
                 "duration_s": 60.0, "success": True,
                 "input_tokens": 100, "output_tokens": 50,
                 "cache_read": 30, "cache_creation": 10},
                {"name": "implementing", "model": "sonnet", "cost_usd": 0.30,
                 "duration_s": 180.0, "success": True,
                 "input_tokens": 500, "output_tokens": 200,
                 "cache_read": 100, "cache_creation": 50},
            ],
        }
        metrics_file.write_text(json.dumps(record) + "\n")
        records = read_phase_records(project_dir)
        assert len(records) == 2
        phases = {r.phase for r in records}
        assert phases == {"planning", "implementing"}
