"""E2E tests for the gate auto-retry flow.

The implementing mock writes a file with a ruff violation (unused import).
The real gate detects it.  The fixing mock cleans it up.
The gate is retried and passes → feature reaches DONE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.metrics import PhaseMetrics
from devflow.core.models import FeatureStatus
from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_build_loop
from devflow.orchestration.lifecycle import start_build

# Ruff violation: unused import (F401).
_BAD_CODE = """\
import os


def nothing() -> None:
    pass
"""

_CLEAN_CODE = """\
def nothing() -> None:
    pass
"""


@pytest.fixture
def mock_claude_gate_retry(
    monkeypatch: pytest.MonkeyPatch,
    mini_python: Path,
) -> None:
    """Implementing writes a ruff violation; fixing removes it.

    On first fixing call: cleans the violation so the second gate pass passes.
    """
    bad_file = mini_python / "src" / "bad_module.py"

    def _fake(  # type: ignore[type-arg]
        feature: object,
        phase: object,
        agent_name: str,
        verbose: bool = False,
        phase_tool_listener: object = None,
        cwd: object = None,
    ) -> tuple:
        del phase_tool_listener, cwd
        if phase.name == "implementing":  # type: ignore[union-attr]
            bad_file.write_text(_BAD_CODE)
        elif phase.name == "fixing":  # type: ignore[union-attr]
            bad_file.write_text(_CLEAN_CODE)
        return True, "Phase completed.", PhaseMetrics()

    monkeypatch.setattr("devflow.orchestration.runner.execute_phase", _fake)


@pytest.mark.e2e
class TestGateAutoRetry:
    def test_feature_reaches_done_after_retry(
        self,
        mini_python: Path,
        mock_claude_gate_retry: None,
        no_github: None,
    ) -> None:
        """Gate fails → fixing inserted → gate retried → DONE."""
        feature = start_build("add nothing function", "quick", mini_python)
        result = execute_build_loop(feature, base=mini_python)

        assert result is True
        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.status == FeatureStatus.DONE

    def test_fixing_phase_was_added(
        self,
        mini_python: Path,
        mock_claude_gate_retry: None,
        no_github: None,
    ) -> None:
        feature = start_build("add nothing function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        phase_names = [p.name for p in f.phases]
        assert "fixing" in phase_names, f"Expected fixing phase, got: {phase_names}"

    def test_gate_retry_counter_incremented(
        self,
        mini_python: Path,
        mock_claude_gate_retry: None,
        no_github: None,
    ) -> None:
        feature = start_build("add nothing function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.metadata.gate_retry >= 1, "gate_retry counter was not incremented"

    def test_bad_file_cleaned_up(
        self,
        mini_python: Path,
        mock_claude_gate_retry: None,
        no_github: None,
    ) -> None:
        """After the full cycle, the ruff violation is gone."""
        feature = start_build("add nothing function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        bad_file = mini_python / "src" / "bad_module.py"
        assert bad_file.exists()
        assert "import os" not in bad_file.read_text()
