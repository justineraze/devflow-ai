"""Tests for the Pi backend and JSONL event parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from devflow.core.backend import Backend, ModelTier
from devflow.core.metrics import PhaseMetrics, ToolUse
from devflow.integrations.pi.backend import PiBackend, parse_event


class TestParseEvent:
    def test_empty_line(self) -> None:
        assert parse_event("") is None
        assert parse_event("   ") is None

    def test_malformed_json(self) -> None:
        assert parse_event("not json") is None

    def test_ignores_unknown_event(self) -> None:
        line = json.dumps({"type": "system_init", "data": {}})
        assert parse_event(line) is None

    def test_tool_execution_start(self) -> None:
        event = {
            "type": "tool_execution_start",
            "toolCallId": "abc123",
            "toolName": "Edit",
            "args": {"file_path": "/path/to/src/devflow/models.py"},
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        kind, payload = result
        assert kind == "tool"
        assert isinstance(payload, ToolUse)
        assert payload.name == "Edit"
        assert "models.py" in payload.summary

    def test_tool_execution_start_bash(self) -> None:
        event = {
            "type": "tool_execution_start",
            "toolCallId": "x",
            "toolName": "Bash",
            "args": {"command": "pytest tests/"},
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        _, payload = result
        assert payload.name == "Bash"
        assert "pytest" in payload.summary

    def test_tool_execution_start_truncates_long_command(self) -> None:
        event = {
            "type": "tool_execution_start",
            "toolCallId": "x",
            "toolName": "Bash",
            "args": {"command": "a" * 200},
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        _, payload = result
        assert len(payload.summary) <= 61

    def test_agent_end_extracts_metrics(self) -> None:
        event = {
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done!"}],
                    "model": "claude-sonnet-4-6",
                    "provider": "anthropic",
                    "usage": {
                        "input": 12000,
                        "output": 800,
                        "cacheRead": 8000,
                        "cacheWrite": 100,
                        "totalTokens": 20900,
                        "cost": {
                            "input": 0.036,
                            "output": 0.012,
                            "cacheRead": 0.008,
                            "cacheWrite": 0.001,
                            "total": 0.056,
                        },
                    },
                    "stopReason": "stop",
                },
            ],
        }
        result = parse_event(json.dumps(event))
        assert result is not None
        kind, payload = result
        assert kind == "metrics"
        assert isinstance(payload, PhaseMetrics)
        assert payload.cost_usd == 0.056
        assert payload.input_tokens == 12000
        assert payload.output_tokens == 800
        assert payload.cache_read == 8000
        assert payload.cache_creation == 100
        assert payload.final_text == "Done!"

    def test_agent_end_no_assistant_message(self) -> None:
        event = {
            "type": "agent_end",
            "messages": [{"role": "user", "content": "hello"}],
        }
        assert parse_event(json.dumps(event)) is None

    def test_ignores_tool_execution_end(self) -> None:
        event = {
            "type": "tool_execution_end",
            "toolCallId": "x",
            "toolName": "Edit",
            "result": "ok",
            "isError": False,
        }
        assert parse_event(json.dumps(event)) is None


class TestPiBackend:
    def test_name(self) -> None:
        assert PiBackend().name == "Pi"

    def test_implements_protocol(self) -> None:
        assert isinstance(PiBackend(), Backend)

    def test_model_name_default(self) -> None:
        backend = PiBackend()
        with patch(
            "devflow.core.config.load_config",
            side_effect=Exception("no config"),
        ):
            assert backend.model_name(ModelTier.FAST) == "anthropic/haiku"
            assert backend.model_name(ModelTier.STANDARD) == "anthropic/sonnet"
            assert backend.model_name(ModelTier.THINKING) == "anthropic/opus"

    def test_model_name_from_config(self) -> None:
        from devflow.core.config import DevflowConfig, PiConfig, PiModelsConfig

        cfg = DevflowConfig(
            pi=PiConfig(
                models=PiModelsConfig(
                    fast="ollama/llama3.1:8b",
                    standard="openai/gpt-4o",
                    thinking="anthropic/opus",
                ),
            ),
        )
        backend = PiBackend()
        with patch(
            "devflow.core.config.load_config", return_value=cfg,
        ):
            assert backend.model_name(ModelTier.FAST) == "ollama/llama3.1:8b"
            assert backend.model_name(ModelTier.STANDARD) == "openai/gpt-4o"
            assert backend.model_name(ModelTier.THINKING) == "anthropic/opus"

    def test_check_available_when_missing(self) -> None:
        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            ok, msg = PiBackend().check_available()
            assert ok is False
            assert "not found" in msg

    def test_one_shot_builds_correct_command(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  result text  \n"

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            result = PiBackend().one_shot(
                system="sys prompt",
                user="user prompt",
                model="anthropic/sonnet",
                timeout=600,
            )

        assert result == "result text"
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["pi", "-p"]
        assert "user prompt" in cmd
        assert "--no-session" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "anthropic/sonnet"
        assert "--system-prompt" in cmd
        sp_idx = cmd.index("--system-prompt")
        assert cmd[sp_idx + 1] == "sys prompt"

    def test_one_shot_without_system(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            PiBackend().one_shot(
                system="", user="prompt", model="anthropic/sonnet", timeout=600,
            )

        cmd = mock_run.call_args[0][0]
        assert "--system-prompt" not in cmd

    def test_execute_builds_correct_command(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        with patch(
            "devflow.integrations.pi.backend.subprocess.Popen",
            return_value=mock_proc,
        ) as mock_popen:
            PiBackend().execute(
                system_prompt="sys",
                user_prompt="do something",
                model="anthropic/sonnet",
                timeout=600,
                cwd=Path("/tmp"),
                env={"PATH": "/usr/bin"},
            )

        cmd = mock_popen.call_args[0][0]
        assert cmd[:2] == ["pi", "-p"]
        assert "do something" in cmd
        assert "--mode" in cmd
        idx = cmd.index("--mode")
        assert cmd[idx + 1] == "json"
        assert "--no-session" in cmd
        assert "--system-prompt" in cmd

    def test_execute_file_not_found(self) -> None:
        with patch(
            "devflow.integrations.pi.backend.subprocess.Popen",
            side_effect=FileNotFoundError,
        ):
            ok, msg, metrics = PiBackend().execute(
                system_prompt="",
                user_prompt="test",
                model="anthropic/sonnet",
                timeout=600,
                cwd=Path("/tmp"),
                env={},
            )
        assert ok is False
        assert "not found" in msg.lower()
        assert isinstance(metrics, PhaseMetrics)

    def test_check_available_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "pi 1.2.3\n"

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            return_value=mock_result,
        ):
            ok, msg = PiBackend().check_available()
        assert ok is True
        assert "1.2.3" in msg

    def test_check_available_error_exit(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            return_value=mock_result,
        ):
            ok, msg = PiBackend().check_available()
        assert ok is False
        assert "some error" in msg

    def test_check_available_timeout(self) -> None:
        import subprocess

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pi", timeout=10),
        ):
            ok, msg = PiBackend().check_available()
        assert ok is False
        assert "timed out" in msg

    def test_one_shot_failure_returns_none(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch(
            "devflow.integrations.pi.backend.subprocess.run",
            return_value=mock_result,
        ):
            assert PiBackend().one_shot(
                system="", user="test", model="anthropic/sonnet", timeout=600,
            ) is None

    def test_execute_success(self) -> None:
        agent_end = json.dumps({
            "type": "agent_end",
            "messages": [{
                "role": "assistant",
                "content": [{"type": "text", "text": "All done"}],
                "usage": {
                    "input": 100, "output": 50,
                    "cacheRead": 0, "cacheWrite": 0,
                    "cost": {"total": 0.01},
                },
            }],
        })

        mock_proc = MagicMock()
        mock_proc.stdout = iter([agent_end + "\n"])
        mock_proc.stderr = iter([])
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        with patch(
            "devflow.integrations.pi.backend.subprocess.Popen",
            return_value=mock_proc,
        ):
            ok, text, metrics = PiBackend().execute(
                system_prompt="",
                user_prompt="test",
                model="anthropic/sonnet",
                timeout=600,
                cwd=Path("/tmp"),
                env={},
            )
        assert ok is True
        assert "All done" in text
        assert metrics.cost_usd == 0.01

    def test_execute_timeout(self) -> None:
        import threading

        block_event = threading.Event()

        def _blocking_stdout():
            """Simulate a stdout that blocks (agent still running)."""
            block_event.wait(timeout=5)
            return
            yield  # make it a generator  # noqa: RET504

        mock_proc = MagicMock()
        mock_proc.stdout = _blocking_stdout()
        mock_proc.stderr = iter([])
        mock_proc.poll = MagicMock(return_value=None)
        mock_proc.kill = MagicMock(side_effect=lambda: block_event.set())
        mock_proc.wait = MagicMock()

        call_count = 0
        def _fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            return 0.0 if call_count == 1 else 20.0

        with (
            patch(
                "devflow.integrations.pi.backend.subprocess.Popen",
                return_value=mock_proc,
            ),
            patch("devflow.integrations.pi.backend._time.monotonic", side_effect=_fake_monotonic),
            patch("devflow.integrations.pi.backend._time.sleep"),
        ):
            ok, msg, metrics = PiBackend().execute(
                system_prompt="",
                user_prompt="test",
                model="anthropic/sonnet",
                timeout=10,
                cwd=Path("/tmp"),
                env={},
            )
        assert ok is False
        assert "timed out" in msg.lower()

    def test_execute_nonzero_exit(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter(["error output\n"])
        mock_proc.returncode = 1
        mock_proc.wait = MagicMock()

        with patch(
            "devflow.integrations.pi.backend.subprocess.Popen",
            return_value=mock_proc,
        ):
            ok, msg, metrics = PiBackend().execute(
                system_prompt="",
                user_prompt="test",
                model="anthropic/sonnet",
                timeout=600,
                cwd=Path("/tmp"),
                env={},
            )
        assert ok is False
        assert "error output" in msg


class TestDrainStream:
    def test_drain_with_tool_and_metrics(self) -> None:
        import queue as q_mod

        from devflow.integrations.pi.backend import _drain_stream

        events: q_mod.Queue[str | None] = q_mod.Queue()
        tool_event = json.dumps({
            "type": "tool_execution_start",
            "toolCallId": "x",
            "toolName": "Read",
            "args": {"file_path": "/a/b.py"},
        })
        metrics_event = json.dumps({
            "type": "agent_end",
            "messages": [{
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input": 10, "output": 5,
                    "cacheRead": 0, "cacheWrite": 0,
                    "cost": {"total": 0.001},
                },
            }],
        })
        events.put(tool_event)
        events.put(metrics_event)
        events.put(None)

        tools_seen: list[ToolUse] = []
        metrics, count, finished = _drain_stream(
            events, lambda t: tools_seen.append(t), PhaseMetrics(), block=True,
        )
        assert count == 1
        assert finished is True
        assert len(tools_seen) == 1
        assert metrics.cost_usd == 0.001
