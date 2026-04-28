"""Tests for the Claude Code backend and Backend protocol."""

from __future__ import annotations

import json

import pytest

from devflow.core.backend import Backend, ModelTier, clear_backend, get_backend, set_backend
from devflow.core.metrics import PhaseMetrics, ToolUse
from devflow.integrations.claude.backend import ClaudeCodeBackend, parse_event


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    """Reset the global backend after each test."""
    yield  # type: ignore[misc]
    clear_backend()


class TestModelTier:
    def test_values(self) -> None:
        assert ModelTier.FAST == "fast"
        assert ModelTier.STANDARD == "standard"
        assert ModelTier.THINKING == "thinking"

    def test_is_str_enum(self) -> None:
        assert isinstance(ModelTier.FAST, str)


class TestClaudeCodeBackend:
    def test_name(self) -> None:
        backend = ClaudeCodeBackend()
        assert backend.name == "Claude Code"

    def test_model_name_fast(self) -> None:
        backend = ClaudeCodeBackend()
        assert backend.model_name(ModelTier.FAST) == "haiku"

    def test_model_name_standard(self) -> None:
        backend = ClaudeCodeBackend()
        assert backend.model_name(ModelTier.STANDARD) == "sonnet"

    def test_model_name_thinking(self) -> None:
        backend = ClaudeCodeBackend()
        assert backend.model_name(ModelTier.THINKING) == "opus"

    def test_implements_protocol(self) -> None:
        backend = ClaudeCodeBackend()
        assert isinstance(backend, Backend)


class TestParseEvent:
    def test_empty_line(self) -> None:
        assert parse_event("") is None
        assert parse_event("   ") is None

    def test_malformed_json(self) -> None:
        assert parse_event("not json") is None

    def test_ignores_system_events(self) -> None:
        line = json.dumps({"type": "system", "subtype": "init"})
        assert parse_event(line) is None

    def test_extracts_read_tool(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/path/to/src/devflow/models.py"},
                    }
                ]
            },
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        kind, payload = result
        assert kind == "tool"
        assert isinstance(payload, ToolUse)
        assert payload.name == "Read"
        assert "models.py" in payload.summary

    def test_extracts_bash_tool(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest tests/"},
                    }
                ]
            },
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        kind, payload = result
        assert kind == "tool"
        assert payload.name == "Bash"
        assert "pytest" in payload.summary

    def test_truncates_long_bash_command(self) -> None:
        long_cmd = "a" * 200
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": long_cmd}}
                ]
            },
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        _, payload = result
        assert len(payload.summary) <= 61  # 60 + ellipsis

    def test_ignores_text_only_assistant(self) -> None:
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        assert parse_event(json.dumps(event)) is None

    def test_extracts_result_metrics(self) -> None:
        event = {
            "type": "result",
            "duration_ms": 12345,
            "total_cost_usd": 0.042,
            "result": "done",
            "usage": {
                "input_tokens": 1234,
                "output_tokens": 567,
                "cache_creation_input_tokens": 4500,
                "cache_read_input_tokens": 89,
            },
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        kind, payload = result
        assert kind == "metrics"
        assert isinstance(payload, PhaseMetrics)
        assert payload.duration_ms == 12345
        assert payload.cost_usd == 0.042
        assert payload.input_tokens == 1234
        assert payload.output_tokens == 567
        assert payload.cache_creation == 4500
        assert payload.cache_read == 89
        assert payload.final_text == "done"


class TestGetSetBackend:
    def test_raises_when_no_backend_registered(self) -> None:
        clear_backend()
        with pytest.raises(RuntimeError, match="No backend registered"):
            get_backend()

    def test_set_backend_overrides(self) -> None:
        class DummyBackend:
            name = "Dummy"

            def model_name(self, tier: ModelTier) -> str:
                return "dummy"

            def execute(self, **kwargs: object) -> tuple[bool, str, PhaseMetrics]:
                return True, "ok", PhaseMetrics()

            def check_available(self) -> tuple[bool, str]:
                return True, "dummy 1.0"

        dummy = DummyBackend()
        set_backend(dummy)  # type: ignore[arg-type]
        assert get_backend() is dummy

    def test_get_backend_caches(self) -> None:
        set_backend(ClaudeCodeBackend())
        b1 = get_backend()
        b2 = get_backend()
        assert b1 is b2
