"""Shared DTOs for phase execution metrics.

Lives in core/ so both orchestration (which produces them) and ui
(which renders them) can depend on it without crossing layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolUse:
    """A tool invocation by Claude during a phase."""

    name: str
    summary: str


@dataclass
class PhaseMetrics:
    """Metrics extracted from Claude Code's stream-json result event."""

    duration_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    tool_count: int = 0
    tools_used: list[ToolUse] = field(default_factory=list)
    final_text: str = ""
