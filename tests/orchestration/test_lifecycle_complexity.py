"""Tests for auto-select workflow integration in lifecycle.start_build."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.core.models import ComplexityScore
from devflow.orchestration.lifecycle import start_build


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Minimal project directory with a .devflow folder."""
    devflow_dir = tmp_path / ".devflow"
    devflow_dir.mkdir()
    return tmp_path


class TestStartBuildAutoWorkflow:
    def test_none_workflow_triggers_scoring(self, project_dir: Path) -> None:
        """When workflow_name is None, score_complexity is called."""
        mock_score = ComplexityScore(files_touched=1, integrations=0, security=0, scope=1)
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
            return_value=mock_score,
        ) as mock_scorer:
            start_build("fix a typo", workflow_name=None, base=project_dir)
        mock_scorer.assert_called_once_with("fix a typo", project_dir)

    def test_explicit_workflow_skips_scoring(self, project_dir: Path) -> None:
        """When workflow_name is explicit, score_complexity is NOT called."""
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
        ) as mock_scorer:
            start_build("fix a typo", workflow_name="standard", base=project_dir)
        mock_scorer.assert_not_called()

    def test_auto_selected_workflow_stored_in_feature(self, project_dir: Path) -> None:
        """The auto-selected workflow is set on the feature object."""
        mock_score = ComplexityScore(files_touched=1, integrations=0, security=0, scope=1)
        # score.workflow will be "light" (total=2)
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
            return_value=mock_score,
        ):
            feature = start_build("add a field", workflow_name=None, base=project_dir)
        assert feature.workflow == mock_score.workflow

    def test_complexity_stored_in_metadata(self, project_dir: Path) -> None:
        """The ComplexityScore is persisted in feature.metadata.complexity."""
        mock_score = ComplexityScore(files_touched=2, integrations=1, security=0, scope=1)
        with patch(
            "devflow.orchestration.lifecycle.score_complexity",
            return_value=mock_score,
        ):
            feature = start_build("add a module", workflow_name=None, base=project_dir)
        assert feature.metadata.complexity is not None
        assert feature.metadata.complexity.total == mock_score.total

    def test_explicit_workflow_no_complexity_in_metadata(self, project_dir: Path) -> None:
        """When user provides an explicit workflow, no score is stored."""
        feature = start_build("test", workflow_name="standard", base=project_dir)
        assert feature.metadata.complexity is None

    def test_auto_workflow_logs_to_console(self, project_dir: Path) -> None:
        """A message is printed to console — verified by mocking the console object."""
        from io import StringIO

        from rich.console import Console

        import devflow.orchestration.lifecycle as lifecycle_mod

        buf = StringIO()
        fake_console = Console(file=buf, force_terminal=False, no_color=True)
        original = lifecycle_mod.console
        lifecycle_mod.console = fake_console

        mock_score = ComplexityScore(files_touched=1, integrations=0, security=0, scope=0)
        try:
            with patch(
                "devflow.orchestration.lifecycle.score_complexity",
                return_value=mock_score,
            ):
                start_build("minor fix", workflow_name=None, base=project_dir)
        finally:
            lifecycle_mod.console = original

        output = buf.getvalue()
        assert "Auto-selected workflow" in output
        assert "quick" in output
        assert "1/12" in output
