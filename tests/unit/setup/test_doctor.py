"""Tests for devflow.setup.doctor — installation diagnostic checks."""

from __future__ import annotations

import json
from pathlib import Path

from devflow.setup.doctor import (
    DoctorReport,
    check_agents_synced,
    check_cli_available,
    check_devflow_init,
    check_hook_installed,
    check_python_version,
    check_skills_synced,
    run_doctor,
)


class TestCheckPythonVersion:
    def test_passes_on_current_runtime(self) -> None:
        result = check_python_version()
        assert result.passed is True
        assert "3." in result.message

    def test_name_is_python(self) -> None:
        result = check_python_version()
        assert result.name == "python"


class TestCheckCliAvailable:
    def test_python3_available(self) -> None:
        result = check_cli_available("python3", ["python3", "--version"])
        assert result.passed is True
        assert "Python" in result.message

    def test_nonexistent_binary(self) -> None:
        result = check_cli_available("nonexistent", ["nonexistent_binary_xyz"])
        assert result.passed is False
        assert "not found" in result.message


class TestCheckAgentsSynced:
    def test_empty_dir(self, tmp_path: Path) -> None:
        result = check_agents_synced(target=tmp_path)
        # Empty dir has 0 of the expected agents.
        assert result.passed is False
        assert "0/" not in result.message or "synced" in result.message

    def test_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        result = check_agents_synced(target=missing)
        assert result.passed is False
        assert "synced" in result.message

    def test_all_synced(self, tmp_path: Path) -> None:
        # Copy all expected agent names into the target dir.
        assets = Path(__file__).resolve().parent.parent / "assets" / "agents"
        if assets.is_dir():
            for f in assets.glob("*.md"):
                (tmp_path / f.name).write_text("# stub")
            result = check_agents_synced(target=tmp_path)
            assert result.passed is True
            assert "synced" in result.message


class TestCheckSkillsSynced:
    def test_empty_dir(self, tmp_path: Path) -> None:
        result = check_skills_synced(target=tmp_path)
        assert result.passed is False

    def test_all_synced(self, tmp_path: Path) -> None:
        assets = Path(__file__).resolve().parent.parent / "assets" / "skills"
        if assets.is_dir():
            for f in assets.glob("*.md"):
                (tmp_path / f.name).write_text("# stub")
            result = check_skills_synced(target=tmp_path)
            assert result.passed is True


class TestCheckDevflowInit:
    def test_missing_dir(self, tmp_path: Path) -> None:
        result = check_devflow_init(base=tmp_path)
        assert result.passed is False
        assert "devflow init" in result.message

    def test_valid_state(self, tmp_path: Path) -> None:
        devflow_dir = tmp_path / ".devflow"
        devflow_dir.mkdir()
        state = {"version": 1, "features": {}, "stack": "python"}
        (devflow_dir / "state.json").write_text(json.dumps(state))
        result = check_devflow_init(base=tmp_path)
        assert result.passed is True
        assert "0 feature" in result.message
        assert "python" in result.message

    def test_corrupt_json(self, tmp_path: Path) -> None:
        devflow_dir = tmp_path / ".devflow"
        devflow_dir.mkdir()
        (devflow_dir / "state.json").write_text("{broken json!!!")
        result = check_devflow_init(base=tmp_path)
        assert result.passed is False
        assert "Invalid" in result.message


class TestCheckClaudeDefaultModel:
    def test_no_settings_file_is_ok(self, tmp_path: Path, monkeypatch) -> None:
        from devflow.setup.doctor import check_claude_default_model

        monkeypatch.setenv("HOME", str(tmp_path))
        result = check_claude_default_model()
        assert result.passed is True
        assert "no settings.json" in result.message

    def test_opus_default_fails_with_hint(self, tmp_path: Path, monkeypatch) -> None:
        import json as _json

        from devflow.setup.doctor import check_claude_default_model

        monkeypatch.setenv("HOME", str(tmp_path))
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(_json.dumps({"model": "opus"}))

        result = check_claude_default_model()
        assert result.passed is False
        assert "sonnet" in result.message

    def test_sonnet_default_is_ok(self, tmp_path: Path, monkeypatch) -> None:
        import json as _json

        from devflow.setup.doctor import check_claude_default_model

        monkeypatch.setenv("HOME", str(tmp_path))
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(_json.dumps({"model": "sonnet"}))

        result = check_claude_default_model()
        assert result.passed is True
        assert "sonnet" in result.message

    def test_invalid_json(self, tmp_path: Path, monkeypatch) -> None:
        from devflow.setup.doctor import check_claude_default_model

        monkeypatch.setenv("HOME", str(tmp_path))
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("not json")

        result = check_claude_default_model()
        assert result.passed is False
        assert "invalid" in result.message.lower()


class TestCheckHookInstalled:
    def _make_hook_and_settings(self, tmp_path: Path) -> tuple[Path, Path]:
        """Return (hooks_dir, settings_file) with hook registered."""
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "devflow-post-compact.sh"
        hook.write_text("#!/usr/bin/env bash\n")
        settings = tmp_path / "settings.json"
        entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": str(hook.resolve())}],
        }
        settings.write_text(json.dumps({"hooks": {"PostCompact": [entry]}}))
        return hooks_dir, settings

    def test_passes_when_script_and_entry_present(self, tmp_path: Path) -> None:
        hooks_dir, settings = self._make_hook_and_settings(tmp_path)
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is True
        assert "PostCompact" in result.message

    def test_fails_when_script_missing(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PostCompact": []}}))
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is False
        assert "devflow install" in result.message

    def test_fails_when_settings_missing(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "devflow-post-compact.sh"
        hook.write_text("#!/usr/bin/env bash\n")
        settings = tmp_path / "settings.json"  # does not exist
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is False
        assert "devflow install" in result.message

    def test_fails_when_entry_missing_from_settings(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "devflow-post-compact.sh"
        hook.write_text("#!/usr/bin/env bash\n")
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"model": "sonnet"}))
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is False

    def test_fails_when_settings_json_malformed(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "devflow-post-compact.sh"
        hook.write_text("#!/usr/bin/env bash\n")
        settings = tmp_path / "settings.json"
        settings.write_text("{bad json!!!")
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is False
        assert "unreadable" in result.message

    def test_fails_with_correct_message_when_settings_empty(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook = hooks_dir / "devflow-post-compact.sh"
        hook.write_text("#!/usr/bin/env bash\n")
        settings = tmp_path / "settings.json"
        settings.write_text("{}")  # exists but empty — not "missing"
        result = check_hook_installed(settings, hooks_dir)
        assert result.passed is False
        # Message should not say "settings.json missing" — the file exists, just empty.
        assert result.message != "settings.json missing — run: devflow install"


class TestRunDoctor:
    def test_returns_report_with_all_checks(self, tmp_path: Path) -> None:
        report = run_doctor(base=tmp_path)
        assert isinstance(report, DoctorReport)
        names = {c.name for c in report.checks}
        assert "python" in names
        assert "Claude Code" in names
        assert "gh" in names
        assert "claude model" in names
        assert "agents" in names
        assert "skills" in names
        assert "hook" in names
        assert "init" in names
        assert len(report.checks) == 8

    def test_empty_report_alias(self) -> None:
        report = DoctorReport()
        assert report.passed is True
        assert len(report.checks) == 0
