"""Schema migrations for persisted files (state.json, config.yaml, metrics.jsonl)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

STATE_VERSION = 1
CONFIG_VERSION = 1
METRICS_VERSION = 2

_Data = dict[str, Any]


def migrate_state(data: _Data, from_version: int, to_version: int) -> _Data:
    """Migrate state.json data from *from_version* to *to_version*."""
    if from_version == to_version:
        return data
    data["version"] = to_version
    return data


def migrate_config(data: _Data, from_version: int, to_version: int) -> _Data:
    """Migrate config.yaml data from *from_version* to *to_version*."""
    if from_version == to_version:
        return data
    data["version"] = to_version
    return data


def migrate_metrics_line(
    line: _Data, from_version: int, to_version: int,
) -> list[_Data]:
    """Migrate a single metrics.jsonl record, returning one or more v2 records.

    A v1 record with nested ``phases[]`` is exploded into N flat v2 records
    (one per phase).  A v2 record passes through as a single-element list.
    """
    if from_version == to_version:
        return [line]

    if from_version == 1 and to_version >= 2:
        return _migrate_v1_to_v2(line)

    line["version"] = to_version
    return [line]


def _migrate_v1_to_v2(record: _Data) -> list[_Data]:
    """Explode a v1 build record into flat v2 per-phase records."""
    phases = record.get("phases") or []
    feature_id = record.get("feature_id", "")
    description = record.get("description", "")
    workflow = record.get("workflow", "")
    success = record.get("success", True)
    timestamp_str = str(record.get("timestamp", ""))

    try:
        base_ts = datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        base_ts = datetime.now(UTC)

    if not phases:
        return [{
            "version": 2,
            "feature_id": feature_id,
            "description": description,
            "workflow": workflow,
            "phase": "unknown",
            "backend": "claude",
            "ts_start": timestamp_str,
            "ts_end": timestamp_str,
            "duration_s": float(record.get("duration_s", 0)),
            "cost_usd": float(record.get("cost_usd", 0)),
            "tokens": {
                "in": int(record.get("input_tokens", 0)),
                "out": int(record.get("output_tokens", 0)),
                "cache_read": int(record.get("cache_read", 0)),
                "cache_creation": int(record.get("cache_creation", 0)),
            },
            "model": "",
            "outcome": "success" if success else "failure",
        }]

    results: list[_Data] = []
    cursor = base_ts
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        dur = float(phase.get("duration_s", 0))
        ts_start = cursor.isoformat()
        cursor = cursor + timedelta(seconds=dur)
        ts_end = cursor.isoformat()
        phase_success = phase.get("success", True)

        results.append({
            "version": 2,
            "feature_id": feature_id,
            "description": description,
            "workflow": workflow,
            "phase": phase.get("name", "unknown"),
            "backend": "claude",
            "ts_start": ts_start,
            "ts_end": ts_end,
            "duration_s": dur,
            "cost_usd": float(phase.get("cost_usd", 0)),
            "tokens": {
                "in": int(phase.get("input_tokens", 0)),
                "out": int(phase.get("output_tokens", 0)),
                "cache_read": int(phase.get("cache_read", 0)),
                "cache_creation": int(phase.get("cache_creation", 0)),
            },
            "model": phase.get("model", ""),
            "outcome": "success" if phase_success else "failure",
        })

    return results
