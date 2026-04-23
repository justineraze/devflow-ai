"""Tests for the Claude Code backend and Backend protocol."""

from __future__ import annotations

import pytest

from devflow.core import backend as _backend_mod
from devflow.core.backend import Backend, ModelTier, get_backend, set_backend
from devflow.core.metrics import PhaseMetrics, ToolUse
from devflow.integrations.claude.backend import ClaudeCodeBackend, parse_event


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    """Reset global backend after each test."""
    yield  # type: ignore[misc]
    _backend_mod._current_backend = None


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
    def test_tool_event(self) -> None:
        line = (
            '{"type":"assistant","message":{"content":'
            '[{"type":"tool_use","name":"Read","input":{"file_path":"src/foo.py"}}]}}'
        )
        result = parse_event(line)
        assert result is not None
        kind, payload = result
        assert kind == "tool"
        assert isinstance(payload, ToolUse)
        assert payload.name == "Read"
        assert "foo.py" in payload.summary

    def test_result_event(self) -> None:
        line = (
            '{"type":"result","duration_ms":1500,"total_cost_usd":0.05,'
            '"result":"done","usage":{"input_tokens":200,"output_tokens":80,'
            '"cache_creation_input_tokens":50,"cache_read_input_tokens":100}}'
        )
        result = parse_event(line)
        assert result is not None
        kind, payload = result
        assert kind == "metrics"
        assert isinstance(payload, PhaseMetrics)
        assert payload.cost_usd == 0.05
        assert payload.input_tokens == 200
        assert payload.cache_creation == 50
        assert payload.cache_read == 100
        assert payload.final_text == "done"

    def test_empty_line(self) -> None:
        assert parse_event("") is None

    def test_malformed_json(self) -> None:
        assert parse_event("not json") is None

    def test_irrelevant_event_type(self) -> None:
        assert parse_event('{"type":"system","data":"ignored"}') is None


class TestGetSetBackend:
    def test_default_is_claude_code(self) -> None:
        backend = get_backend()
        assert isinstance(backend, ClaudeCodeBackend)

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
        b1 = get_backend()
        b2 = get_backend()
        assert b1 is b2
