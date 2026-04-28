"""Tests for complexity score rendering in devflow.ui.display."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from devflow.core.models import (
    ComplexityScore,
    Feature,
    FeatureMetadata,
    FeatureStatus,
    WorkflowState,
)
from devflow.ui.display import render_feature_detail, render_status_table


def _capture(func, *args) -> str:  # noqa: ANN001
    """Capture Rich console output by temporarily replacing the module console."""
    import devflow.ui.display as display_mod

    original = display_mod.console
    buf = StringIO()
    display_mod.console = Console(file=buf, force_terminal=False, width=160, no_color=True)
    try:
        func(*args)
    finally:
        display_mod.console = original
    return buf.getvalue()


def _make_feature(
    workflow: str = "standard",
    complexity: ComplexityScore | None = None,
) -> Feature:
    meta = FeatureMetadata(complexity=complexity)
    return Feature(
        id="feat-001",
        description="Test feature",
        status=FeatureStatus.IMPLEMENTING,
        workflow=workflow,
        metadata=meta,
    )


class TestRenderFeatureDetailComplexity:
    def test_score_line_present_when_complexity_set(self) -> None:
        score = ComplexityScore(files_touched=2, integrations=1, security=1, scope=1)
        feature = _make_feature("standard", complexity=score)
        output = _capture(render_feature_detail, feature)
        assert "Complexity:" in output
        assert "5/12" in output
        assert "files:2" in output
        assert "integrations:1" in output
        assert "security:1" in output
        assert "scope:1" in output

    def test_score_shows_workflow_arrow(self) -> None:
        score = ComplexityScore(files_touched=1, integrations=0, security=0, scope=0)
        feature = _make_feature("quick", complexity=score)
        output = _capture(render_feature_detail, feature)
        assert "→" in output
        assert "quick" in output

    def test_score_line_absent_when_no_complexity(self) -> None:
        feature = _make_feature("standard", complexity=None)
        output = _capture(render_feature_detail, feature)
        assert "Complexity:" not in output

    def test_workflow_line_always_present(self) -> None:
        feature = _make_feature("light", complexity=None)
        output = _capture(render_feature_detail, feature)
        assert "Workflow:" in output
        assert "light" in output


class TestRenderStatusTableComplexity:
    def test_table_shows_score_suffix_when_complexity_set(self) -> None:
        score = ComplexityScore(files_touched=2, integrations=2, security=1, scope=1)
        feature = _make_feature("standard", complexity=score)
        state = WorkflowState()
        state.add_feature(feature)
        output = _capture(render_status_table, state)
        # Total is 6 → "standard (6/12)"
        assert "6/12" in output

    def test_table_shows_plain_workflow_when_no_complexity(self) -> None:
        feature = _make_feature("standard", complexity=None)
        state = WorkflowState()
        state.add_feature(feature)
        output = _capture(render_status_table, state)
        assert "standard" in output
        # No score suffix
        assert "/12" not in output
