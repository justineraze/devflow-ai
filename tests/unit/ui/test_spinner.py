"""Tests for devflow.ui.spinner — PhaseSpinner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from devflow.core.formatting import tool_icon
from devflow.ui.spinner import PhaseSpinner


class TestToolIcon:
    def test_read_returns_book(self) -> None:
        assert tool_icon("Read") == "📖"

    def test_bash_returns_terminal(self) -> None:
        assert tool_icon("Bash") == "💻"

    def test_grep_returns_magnifier(self) -> None:
        assert tool_icon("Grep") == "🔍"

    def test_unknown_returns_wrench(self) -> None:
        assert tool_icon("SomeUnknownTool") == "🔧"

    def test_case_insensitive_prefix_fallback(self) -> None:
        # "WRITE" doesn't match exact key "Write", but case-insensitive prefix works
        assert tool_icon("WRITE") == "📝"


class TestPhaseSpinner:
    @patch("devflow.ui.spinner.Live")
    def test_update_changes_renderable(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        spinner = PhaseSpinner("implementing")
        spinner.update("Read", "models.py")

        mock_live.update.assert_called_once()
        rendered: object = mock_live.update.call_args[0][0]
        # The renderable should encode tool name and summary.
        assert "Read" in str(rendered)
        assert "models.py" in str(rendered)

    @patch("devflow.ui.spinner.Live")
    def test_update_shows_phase_name(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        spinner = PhaseSpinner("planning")
        spinner.update("Bash", "pytest -q")

        rendered: object = mock_live.update.call_args[0][0]
        assert "planning" in str(rendered)

    @patch("devflow.ui.spinner.Live")
    def test_multiple_updates_show_last(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        spinner = PhaseSpinner("implementing")
        spinner.update("Read", "first.py")
        spinner.update("Write", "second.py")

        # Only the last call matters for the live display.
        assert mock_live.update.call_count == 2
        last_rendered = mock_live.update.call_args[0][0]
        assert "Write" in str(last_rendered)
        assert "second.py" in str(last_rendered)

    @patch("devflow.ui.spinner.Live")
    def test_stop_calls_live_stop(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        spinner = PhaseSpinner("gate")
        spinner.stop()

        mock_live.stop.assert_called_once()

    @patch("devflow.ui.spinner.Live")
    def test_stop_skips_if_not_started(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = False
        mock_live_cls.return_value = mock_live

        spinner = PhaseSpinner("gate")
        spinner.stop()  # Should not raise.

        mock_live.stop.assert_not_called()

    @patch("devflow.ui.spinner.Live")
    def test_context_manager_starts_and_stops(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        with PhaseSpinner("reviewing"):
            mock_live.start.assert_called_once()

        mock_live.stop.assert_called_once()

    @patch("devflow.ui.spinner.Live")
    def test_context_manager_stops_on_exception(self, mock_live_cls: MagicMock) -> None:
        mock_live = MagicMock()
        mock_live.is_started = True
        mock_live_cls.return_value = mock_live

        with pytest.raises(ValueError), PhaseSpinner("fixing"):
            raise ValueError("boom")

        mock_live.stop.assert_called_once()
