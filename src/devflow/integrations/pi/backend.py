"""Pi backend — subprocess execution and JSONL event parsing."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time as _time
from pathlib import Path
from typing import IO, Any

import structlog

from devflow.core.backend import ModelTier, OnToolEvent
from devflow.core.errors import BackendError
from devflow.core.metrics import PhaseMetrics, ToolUse
from devflow.core.paths import venv_env

log = structlog.get_logger(__name__)

ERR_CLI_NOT_FOUND = (
    "✗ Pi CLI not found — 'pi' is not in PATH"
    " — Fix: install it from https://github.com/badlogic/pi-mono"
)
ERR_TIMEOUT_TEMPLATE = (
    "✗ Phase timed out after {timeout}s — the agent ran too long"
    " — Fix: increase the timeout in your workflow YAML or split the feature"
)

# Default model mapping (Anthropic via Pi) — overridden by config.
_DEFAULT_MODEL_MAP: dict[ModelTier, str] = {
    ModelTier.FAST: "anthropic/haiku",
    ModelTier.STANDARD: "anthropic/sonnet",
    ModelTier.THINKING: "anthropic/opus",
}


# ── JSONL event parsing ──────────────────────────────────────────────


def _summarize_tool_use(tool_name: str, args: dict[str, Any]) -> str:
    """Build a concise one-line summary of a Pi tool invocation."""
    match tool_name:
        case "Read" | "Write" | "Edit":
            path = str(args.get("file_path", args.get("path", "")))
            short = path.rsplit("/", 2)
            return "/".join(short[-2:]) if len(short) > 1 else path
        case "Bash":
            cmd = str(args.get("command", ""))
            return cmd[:60] + ("…" if len(cmd) > 60 else "")
        case _:
            return str(args.get("pattern", args.get("description", "")))[:60]


def parse_event(line: str) -> tuple[str, Any] | None:
    """Parse a single Pi JSONL event line.

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

    if event_type == "tool_execution_start":
        name = event.get("toolName", "?")
        summary = _summarize_tool_use(name, event.get("args", {}))
        return ("tool", ToolUse(name=name, summary=summary))

    if event_type == "agent_end":
        messages = event.get("messages", [])
        assistant_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                assistant_msg = msg
                break
        if assistant_msg is None:
            return None

        usage = assistant_msg.get("usage", {})
        cost = usage.get("cost", {})

        final_text = ""
        for item in assistant_msg.get("content", []):
            if item.get("type") == "text":
                final_text = item.get("text", "")
                break

        return ("metrics", PhaseMetrics(
            cost_usd=cost.get("total", 0.0),
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            cache_read=usage.get("cacheRead", 0),
            cache_creation=usage.get("cacheWrite", 0),
            final_text=final_text,
        ))

    return None


# ── Backend implementation ──────────────────────────────────────────


def _reader_thread(stream: IO[str], q: queue.Queue[str | None]) -> None:
    """Drain *stream* line by line into *q*, then push a None sentinel."""
    try:
        for line in stream:
            q.put(line)
    finally:
        q.put(None)


def _stderr_drain_thread(stream: IO[str], buf: list[str]) -> None:
    """Drain stderr into *buf* so the kernel pipe never fills up."""
    try:
        for line in stream:
            buf.append(line)
    except (OSError, ValueError):
        pass


def _drain_stream(
    q: queue.Queue[str | None],
    on_tool: OnToolEvent | None,
    metrics: PhaseMetrics,
    *,
    block: bool,
) -> tuple[PhaseMetrics, int, bool]:
    """Pop events from *q* and update *metrics* / fire *on_tool*."""
    tool_count = metrics.tool_count
    finished = False
    while True:
        try:
            line = q.get(block=block)
        except queue.Empty:
            break
        if line is None:
            finished = True
            break
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
    return metrics, tool_count, finished


class PiBackend:
    """Runs phases via the ``pi`` CLI with JSONL output."""

    @property
    def name(self) -> str:
        return "Pi"

    def model_name(self, tier: ModelTier) -> str:
        """Map a logical tier to a Pi model string, reading from config."""
        try:
            from devflow.core.config import load_config

            config = load_config()
            pi_cfg = config.pi
            mapping = {
                ModelTier.FAST: pi_cfg.models.fast,
                ModelTier.STANDARD: pi_cfg.models.standard,
                ModelTier.THINKING: pi_cfg.models.thinking,
            }
            return mapping[tier]
        except Exception:
            return _DEFAULT_MODEL_MAP[tier]

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
        """Execute a phase via ``pi -p`` and stream JSONL output."""
        cmd = [
            "pi", "-p", user_prompt,
            "--mode", "json",
            "--no-session",
            "--model", model,
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd),
                env=env,
            )
        except FileNotFoundError:
            return False, ERR_CLI_NOT_FOUND, PhaseMetrics()

        if proc.stdout is None or proc.stderr is None:
            raise BackendError(
                "✗ Subprocess pipes failed to open — Popen returned None streams"
                " — Fix: check system resources and retry"
            )

        events: queue.Queue[str | None] = queue.Queue()
        stderr_buf: list[str] = []
        reader = threading.Thread(
            target=_reader_thread, args=(proc.stdout, events), daemon=True,
        )
        stderr_reader = threading.Thread(
            target=_stderr_drain_thread, args=(proc.stderr, stderr_buf),
            daemon=True,
        )
        reader.start()
        stderr_reader.start()

        metrics = PhaseMetrics()

        deadline = _time.monotonic() + timeout
        while True:
            metrics, _, finished = _drain_stream(events, on_tool, metrics, block=False)
            if finished:
                break
            ret = proc.poll()
            if ret is not None:
                metrics, _, _ = _drain_stream(events, on_tool, metrics, block=True)
                break
            if _time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                metrics, _, _ = _drain_stream(events, on_tool, metrics, block=False)
                return False, ERR_TIMEOUT_TEMPLATE.format(timeout=timeout), metrics
            _time.sleep(0.1)

        proc.wait()
        reader.join(timeout=1.0)
        stderr_reader.join(timeout=1.0)

        if proc.returncode == 0:
            return True, metrics.final_text or "Phase completed", metrics

        if stderr_reader.is_alive():
            log.warning(
                "pi stderr drain thread still alive after 1s join; "
                "error message may be truncated.",
            )
        stderr_text = "".join(stderr_buf).strip()
        return False, stderr_text or metrics.final_text or "Unknown error", metrics

    def one_shot(
        self,
        *,
        system: str,
        user: str,
        model: str,
        timeout: int,
    ) -> str | None:
        """Run a one-shot Pi prompt and return trimmed text, or None."""
        cmd = ["pi", "-p", user, "--no-session", "--model", model]
        if system:
            cmd.extend(["--system-prompt", system])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path.cwd()),
                env=venv_env(Path.cwd()),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            log.debug("one_shot: pi call failed", exc_info=True)
        return None

    def check_available(self) -> tuple[bool, str]:
        """Verify the ``pi`` CLI is installed and reachable."""
        try:
            result = subprocess.run(
                ["pi", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip().split("\n")[0]
                return True, version
            return False, result.stderr.strip() or "pi exited with error"
        except FileNotFoundError:
            return False, "pi CLI not found in PATH"
        except subprocess.TimeoutExpired:
            return False, "pi --version timed out"
