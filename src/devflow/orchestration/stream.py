"""Stream-JSON parser for Claude Code live progress display."""

from __future__ import annotations

import json
from typing import Any

from devflow.core.formatting import format_cost, format_tokens, format_tool_line
from devflow.core.metrics import PhaseMetrics, ToolUse

__all__ = [
    "PhaseMetrics",
    "ToolUse",
    "format_cost",
    "format_tokens",
    "format_tool_line",
    "parse_event",
]


def _summarize_tool_use(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build a concise one-line summary of a tool invocation."""
    if tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", "")
        # Show only the relative part after src/ or the filename.
        short = path.rsplit("/", 2)
        return "/".join(short[-2:]) if len(short) > 1 else path
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:60] + ("…" if len(cmd) > 60 else "")
    if tool_name in ("Grep", "Glob"):
        return tool_input.get("pattern", "")[:60]
    if tool_name == "Task":
        return tool_input.get("description", "")[:60]
    if tool_name == "TodoWrite":
        todos = tool_input.get("todos", [])
        active = next((t for t in todos if t.get("status") == "in_progress"), None)
        if active:
            label = active.get("activeForm") or active.get("content", "")
            return label[:60]
        return f"{len(todos)} todos"
    return ""


def parse_event(line: str) -> tuple[str, Any] | None:
    """Parse a single stream-json line.

    Returns a tuple (kind, payload) where kind is one of:
    - "tool": payload is a ToolUse
    - "metrics": payload is a PhaseMetrics (final)
    - None: irrelevant event

    Returns None for malformed or uninteresting lines.
    """
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = event.get("type")

    # Tool invocations come through assistant messages.
    if event_type == "assistant":
        content = event.get("message", {}).get("content", [])
        for item in content:
            if item.get("type") == "tool_use":
                name = item.get("name", "?")
                summary = _summarize_tool_use(name, item.get("input", {}))
                return ("tool", ToolUse(name=name, summary=summary))

    # Final result with metrics.
    if event_type == "result":
        usage = event.get("usage", {})
        return ("metrics", PhaseMetrics(
            duration_ms=event.get("duration_ms", 0),
            cost_usd=event.get("total_cost_usd", 0.0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read=usage.get("cache_read_input_tokens", 0),
            final_text=event.get("result", ""),
        ))

    return None


