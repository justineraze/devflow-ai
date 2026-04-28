"""Tests for devflow.core.stack — StackPlugin Protocol."""

from __future__ import annotations

from pathlib import Path

from devflow.core.stack import StackPlugin


class _DummyStack:
    """Minimal StackPlugin implementation for runtime_checkable tests."""

    @property
    def name(self) -> str:
        return "dummy"

    def detect(self, project_root: Path) -> bool:
        return True

    def agent_name(self) -> str:
        return "developer-dummy"

    def gate_commands(self) -> list[tuple[str, list[str]]]:
        return [("lint", ["echo", "ok"])]


class TestStackPluginProtocol:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_DummyStack(), StackPlugin)

    def test_non_plugin_fails_isinstance(self) -> None:
        assert not isinstance(object(), StackPlugin)

    def test_detect_returns_bool(self) -> None:
        plugin = _DummyStack()
        assert plugin.detect(Path("/tmp")) is True

    def test_agent_name(self) -> None:
        plugin = _DummyStack()
        assert plugin.agent_name() == "developer-dummy"

    def test_gate_commands(self) -> None:
        plugin = _DummyStack()
        cmds = plugin.gate_commands()
        assert len(cmds) == 1
        assert cmds[0] == ("lint", ["echo", "ok"])
