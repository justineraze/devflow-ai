"""E2E tests for the quick workflow (implement + gate).

The gate runs for real (ruff + pytest on the mini_python fixture).
claude -p is mocked — only the orchestration layer is exercised.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from devflow.core.models import FeatureStatus, PhaseStatus
from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_build_loop
from devflow.orchestration.lifecycle import start_build


@pytest.mark.e2e
class TestQuickWorkflow:
    def test_feature_reaches_done(
        self, mini_python: Path, mock_claude: None, no_github: None,
    ) -> None:
        feature = start_build("add subtract function", "quick", mini_python)
        result = execute_build_loop(feature, base=mini_python)

        assert result is True
        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.status == FeatureStatus.DONE

    def test_all_phases_complete(
        self, mini_python: Path, mock_claude: None, no_github: None,
    ) -> None:
        feature = start_build("add subtract function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        for phase in f.phases:
            assert phase.status == PhaseStatus.DONE, (
                f"Phase {phase.name!r} is {phase.status!r}, expected done"
            )

    def test_git_branch_created(
        self, mini_python: Path, mock_claude: None, no_github: None,
    ) -> None:
        feature = start_build("add subtract function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        result = subprocess.run(
            ["git", "branch", "--list"],
            capture_output=True, text=True, cwd=mini_python,
        )
        branches = result.stdout
        assert "feat/" in branches, f"Expected a feat/ branch, got: {branches!r}"

    def test_files_json_artifact_written(
        self, mini_python: Path, mock_claude: None, no_github: None,
    ) -> None:
        feature = start_build("add subtract function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        artifact = mini_python / ".devflow" / feature.id / "files.json"
        assert artifact.exists(), "files.json artifact was not created"
        data = json.loads(artifact.read_text())
        assert "paths" in data
        assert "critical_paths" in data

    def test_gate_json_artifact_written(
        self, mini_python: Path, mock_claude: None, no_github: None,
    ) -> None:
        feature = start_build("add subtract function", "quick", mini_python)
        execute_build_loop(feature, base=mini_python)

        artifact = mini_python / ".devflow" / feature.id / "gate.json"
        assert artifact.exists(), "gate.json artifact was not created"
        data = json.loads(artifact.read_text())
        assert data["passed"] is True
