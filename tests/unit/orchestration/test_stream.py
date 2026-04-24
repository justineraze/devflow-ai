"""Tests for devflow.orchestration.stream — Claude Code stream-json parser."""

import json

from devflow.integrations.claude.backend import parse_event
from devflow.orchestration.stream import (
    ToolUse,
    format_cost,
    format_tokens,
    format_tool_line,
)


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
        _, payload = parse_event(json.dumps(event))
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
        assert payload.duration_ms == 12345
        assert payload.cost_usd == 0.042
        assert payload.input_tokens == 1234
        assert payload.output_tokens == 567
        assert payload.cache_creation == 4500
        assert payload.cache_read == 89
        assert payload.final_text == "done"


class TestFormatters:
    def test_format_cost_cents(self) -> None:
        assert format_cost(0.005) == "0.5¢"
        assert format_cost(0.003) == "0.3¢"

    def test_format_cost_dollars(self) -> None:
        assert format_cost(0.12) == "$0.12"
        assert format_cost(1.50) == "$1.50"

    def test_format_tokens_small(self) -> None:
        assert format_tokens(42) == "42"
        assert format_tokens(999) == "999"

    def test_format_tokens_thousands(self) -> None:
        assert format_tokens(1234) == "1.2k"
        assert format_tokens(15000) == "15.0k"

    def test_format_tool_line_with_icon(self) -> None:
        tool = ToolUse(name="Read", summary="models.py")
        line = format_tool_line(tool)
        assert "Read" in line
        assert "models.py" in line
        assert "📖" in line

    def test_format_tool_line_unknown_tool(self) -> None:
        tool = ToolUse(name="UnknownTool", summary="stuff")
        line = format_tool_line(tool)
        assert "UnknownTool" in line
        assert "🔧" in line
