"""Tests for devflow.setup._settings — atomic JSON helpers."""

from __future__ import annotations

import json
from pathlib import Path

from devflow.setup._settings import load_settings, write_settings_atomic


class TestLoadSettings:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        data, err = load_settings(tmp_path / "nonexistent.json")
        assert data == {}
        assert err is None

    def test_valid_json_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        payload = {"model": "sonnet", "hooks": {}}
        path.write_text(json.dumps(payload))
        data, err = load_settings(path)
        assert data == payload
        assert err is None

    def test_malformed_json_returns_error(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{broken!!")
        data, err = load_settings(path)
        assert data == {}
        assert err is not None
        assert "invalid JSON" in err


class TestWriteSettingsAtomic:
    def test_writes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        write_settings_atomic(path, {"key": "value"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"key": "value"}

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "settings.json"
        write_settings_atomic(path, {})
        assert path.exists()

    def test_no_tmp_file_left_on_success(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        write_settings_atomic(path, {"a": 1})
        tmp_files = list(tmp_path.glob(".settings-*.tmp"))
        assert tmp_files == []

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"old": True}))
        write_settings_atomic(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
