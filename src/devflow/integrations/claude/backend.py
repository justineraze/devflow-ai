"""Claude Code backend — subprocess execution and stream-json parsing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from devflow.core.backend import ModelTier, OnToolEvent
from devflow.core.metrics import PhaseMetrics, ToolUse

# Claude Code model aliases indexed by logical tier.
_MODEL_MAP: dict[ModelTier, str] = {
    ModelTier.FAST: "haiku",
    ModelTier.STANDARD: "sonnet",
    ModelTier.THINKING: "opus",
}


# ── Stream-json parsing ────────────────────────────────────────────


def _summarize_tool_use(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build a concise one-line summary of a tool invocation."""
    match tool_name:
        case "Read" | "Write" | "Edit":
            path = tool_input.get("file_path", "")
            short = path.rsplit("/", 2)
            return "/".join(short[-2:]) if len(short) > 1 else path
        case "Bash":
            cmd = tool_input.get("command", "")
            return cmd[:60] + ("…" if len(cmd) > 60 else "")
        case "Grep" | "Glob":
            return tool_input.get("pattern", "")[:60]
        case "Task":
            return tool_input.get("description", "")[:60]
        case "TodoWrite":
            todos = tool_input.get("todos", [])
            active = next((t for t in todos if t.get("status") == "in_progress"), None)
            if active:
                label = active.get("activeForm") or active.get("content", "")
                return label[:60]
            return f"{len(todos)} todos"
        case _:
            return ""


def parse_event(line: str) -> tuple[str, Any] | None:
    """Parse a single Claude Code stream-json line.

    Returns ``("tool", ToolUse)`` or ``("metrics", PhaseMetrics)``
    or ``None`` for irrelevant lines.
    """
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = event.get("type")

    if event_type == "assistant":
        content = event.get("message", {}).get("content", [])
        for item in content:
            if item.get("type") == "tool_use":
                name = item.get("name", "?")
                summary = _summarize_tool_use(name, item.get("input", {}))
                return ("tool", ToolUse(name=name, summary=summary))

    if event_type == "result":
        usage = event.get("usage", {})
        return ("metrics", PhaseMetrics(
            duration_ms=event.get("duration_ms", 0),
            cost_usd=event.get("total_cost_usd", 0.0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation=usage.get("cache_creation_input_tokens", 0),
            cache_read=usage.get("cache_read_input_tokens", 0),
            final_text=event.get("result", ""),
        ))

    return None


# ── Backend implementation ──────────────────────────────────────────


class ClaudeCodeBackend:
    """Runs phases via the ``claude`` CLI with stream-json output."""

    @property
    def name(self) -> str:
        return "Claude Code"

    def model_name(self, tier: ModelTier) -> str:
        return _MODEL_MAP[tier]

    def execute(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        timeout: int,
        cwd: Path,
        env: dict[str, str],
        on_tool: OnToolEvent | None = None,
    ) -> tuple[bool, str, PhaseMetrics]:
        """Execute a phase via ``claude -p`` and stream output."""
        cmd = [
            "claude", "-p", "-",
            "--model", model,
            "--permission-mode", "acceptEdits",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd),
                env=env,
            )

            proc.stdin.write(user_prompt)
            proc.stdin.close()

            metrics = PhaseMetrics()
            tool_count = 0

            for line in proc.stdout:
                parsed = parse_event(line)
                if not parsed:
                    continue
                kind, payload = parsed
                if kind == "tool":
                    tool_count += 1
                    if on_tool is not None:
                        on_tool(payload)
                elif kind == "metrics":
                    metrics = payload
                    metrics.tool_count = tool_count

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return False, (
                    f"Phase timed out after {timeout}s. "
                    "Increase the timeout in your workflow YAML or split the feature."
                ), metrics

            if proc.returncode == 0:
                return True, metrics.final_text or "Phase completed", metrics
            stderr = proc.stderr.read().strip()
            return False, stderr or metrics.final_text or "Unknown error", metrics

        except FileNotFoundError:
            return False, (
                "Claude Code CLI not found. "
                "Install it: https://docs.anthropic.com/en/docs/claude-code"
            ), PhaseMetrics()

    def one_shot(
        self,
        *,
        system: str,
        user: str,
        model: str,
        timeout: int,
    ) -> str | None:
        """Run a one-shot Claude prompt and return trimmed text, or None."""
        from devflow.core.paths import venv_env

        cmd = [
            "claude", "-p", "-",
            "--model", model,
            "--output-format", "text",
        ]
        if system:
            cmd.extend(["--system-prompt", system])

        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path.cwd()),
                env=venv_env(Path.cwd()),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def check_available(self) -> tuple[bool, str]:
        """Verify the ``claude`` CLI is installed and reachable."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip().split("\n")[0]
                return True, version
            return False, result.stderr.strip() or "claude exited with error"
        except FileNotFoundError:
            return False, "claude CLI not found in PATH"
        except subprocess.TimeoutExpired:
            return False, "claude --version timed out"
