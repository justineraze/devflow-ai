"""Tests for StackPlugin implementations in devflow.integrations.detect."""

from __future__ import annotations

import json
from pathlib import Path

from devflow.core.stack import StackPlugin
from devflow.integrations.detect import (
    FrontendStack,
    PhpStack,
    PythonStack,
    TypeScriptStack,
    get_stack_plugin,
)


class TestPluginProtocolConformance:
    def test_python_satisfies_protocol(self) -> None:
        assert isinstance(PythonStack(), StackPlugin)

    def test_typescript_satisfies_protocol(self) -> None:
        assert isinstance(TypeScriptStack(), StackPlugin)

    def test_php_satisfies_protocol(self) -> None:
        assert isinstance(PhpStack(), StackPlugin)

    def test_frontend_satisfies_protocol(self) -> None:
        assert isinstance(FrontendStack(), StackPlugin)


class TestPythonStack:
    def test_name(self) -> None:
        assert PythonStack().name == "python"

    def test_agent_name(self) -> None:
        assert PythonStack().agent_name() == "developer-python"

    def test_detect_python_project(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").touch()
        assert PythonStack().detect(tmp_path) is True

    def test_detect_non_python(self, tmp_path: Path) -> None:
        (tmp_path / "main.ts").touch()
        assert PythonStack().detect(tmp_path) is False

    def test_gate_commands(self) -> None:
        cmds = PythonStack().gate_commands()
        names = [c[0] for c in cmds]
        assert "ruff" in names
        assert "pytest" in names


class TestTypeScriptStack:
    def test_name(self) -> None:
        assert TypeScriptStack().name == "typescript"

    def test_agent_name(self) -> None:
        assert TypeScriptStack().agent_name() == "developer-typescript"

    def test_detect_ts_project(self, tmp_path: Path) -> None:
        (tmp_path / "index.ts").touch()
        assert TypeScriptStack().detect(tmp_path) is True

    def test_detect_ts_with_framework_is_not_typescript(self, tmp_path: Path) -> None:
        (tmp_path / "index.ts").touch()
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18"},
        }))
        assert TypeScriptStack().detect(tmp_path) is False


class TestFrontendStack:
    def test_name(self) -> None:
        assert FrontendStack().name == "frontend"

    def test_agent_name(self) -> None:
        assert FrontendStack().agent_name() == "developer-frontend"

    def test_detect_with_framework(self, tmp_path: Path) -> None:
        (tmp_path / "index.tsx").touch()
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18"},
        }))
        assert FrontendStack().detect(tmp_path) is True

    def test_detect_without_framework(self, tmp_path: Path) -> None:
        (tmp_path / "index.tsx").touch()
        assert FrontendStack().detect(tmp_path) is False


class TestPhpStack:
    def test_name(self) -> None:
        assert PhpStack().name == "php"

    def test_agent_name(self) -> None:
        assert PhpStack().agent_name() == "developer-php"

    def test_detect_php_project(self, tmp_path: Path) -> None:
        (tmp_path / "index.php").touch()
        assert PhpStack().detect(tmp_path) is True


class TestGetStackPlugin:
    def test_get_known_plugin(self) -> None:
        plugin = get_stack_plugin("python")
        assert plugin is not None
        assert plugin.name == "python"

    def test_get_unknown_returns_none(self) -> None:
        assert get_stack_plugin("unknown") is None
