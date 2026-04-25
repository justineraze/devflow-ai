"""Tests for devflow.core.formatting — pure display formatters."""

from __future__ import annotations

from devflow.core.formatting import (
    format_cost,
    format_duration,
    format_tokens,
    format_tool_line,
    tool_icon,
)
from devflow.core.metrics import ToolUse


class TestFormatCost:
    def test_zero(self) -> None:
        assert format_cost(0) == "$0.00"

    def test_cents(self) -> None:
        assert format_cost(0.005) == "0.5¢"
        assert format_cost(0.003) == "0.3¢"

    def test_dollars(self) -> None:
        assert format_cost(0.12) == "$0.12"
        assert format_cost(1.50) == "$1.50"

    def test_negative(self) -> None:
        assert format_cost(-0.42) == "-$0.42"


class TestFormatTokens:
    def test_small(self) -> None:
        assert format_tokens(42) == "42"
        assert format_tokens(999) == "999"

    def test_thousands(self) -> None:
        assert format_tokens(1234) == "1.2k"
        assert format_tokens(15000) == "15.0k"


class TestFormatDuration:
    def test_none(self) -> None:
        assert format_duration(None) == "—"

    def test_milliseconds(self) -> None:
        assert format_duration(0.42) == "420ms"

    def test_seconds(self) -> None:
        assert format_duration(3.7) == "4s"

    def test_minutes_and_seconds(self) -> None:
        assert format_duration(90) == "1m30s"


class TestToolIcon:
    def test_known_tool(self) -> None:
        assert tool_icon("Read") == "📖"
        assert tool_icon("Bash") == "💻"

    def test_unknown_tool_falls_back(self) -> None:
        assert tool_icon("UnknownTool") == "🔧"

    def test_prefix_match(self) -> None:
        # "ReadFile" should match the "Read" prefix.
        assert tool_icon("ReadFile") == "📖"


class TestFormatToolLine:
    def test_with_summary(self) -> None:
        line = format_tool_line(ToolUse(name="Read", summary="models.py"))
        assert "Read" in line
        assert "models.py" in line
        assert "📖" in line

    def test_unknown_tool(self) -> None:
        line = format_tool_line(ToolUse(name="UnknownTool", summary="stuff"))
        assert "UnknownTool" in line
        assert "🔧" in line
