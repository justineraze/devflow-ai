"""Display formatters for costs, tokens, and tool actions.

Pure formatting — no Rich dependency, no I/O. Shared by the stream
parser (verbose mode), the spinner (live mode), and the build summary.
"""

from __future__ import annotations

from devflow.core.metrics import ToolUse

# Canonical icon mapping for Claude Code tools (exact name match).
TOOL_ICONS: dict[str, str] = {
    "Read": "📖",
    "Write": "📝",
    "Edit": "📝",
    "Bash": "💻",
    "Grep": "🔍",
    "Glob": "🔍",
    "Task": "🤖",
    "TodoWrite": "📋",
    "WebFetch": "🌐",
    "WebSearch": "🌐",
    "Agent": "🤖",
}


def tool_icon(tool_name: str) -> str:
    """Return an emoji for *tool_name*.

    Tries exact match first, then case-insensitive prefix match as fallback.
    """
    icon = TOOL_ICONS.get(tool_name)
    if icon:
        return icon
    key = tool_name.lower()
    for name, ico in TOOL_ICONS.items():
        if key.startswith(name.lower()):
            return ico
    return "🔧"


def format_duration(seconds: float | None) -> str:
    """Format seconds as human-readable duration (e.g. '42ms', '3s', '1m30s')."""
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{int(round(seconds))}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def format_cost(cost_usd: float) -> str:
    """Format a cost in USD for display."""
    if cost_usd == 0:
        return "$0.00"
    if cost_usd < 0.01:
        cents = cost_usd * 100
        return f"{cents:.1f}¢"
    return f"${cost_usd:.2f}"


def format_tokens(n: int) -> str:
    """Format a token count (e.g. 3421 -> '3.4k')."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k"


def format_tool_line(tool: ToolUse, indent: str = "  ") -> str:
    """Format a tool use as an aligned, indented progress line.

    Layout: ``{indent}{icon}  {NAME:8}  {summary}``. Fixed-width name
    column keeps summaries aligned across the whole phase log.
    """
    icon = tool_icon(tool.name)
    name_col = tool.name.ljust(8)
    if tool.summary:
        return f"{indent}{icon}  {name_col}  {tool.summary}"
    return f"{indent}{icon}  {name_col}"
