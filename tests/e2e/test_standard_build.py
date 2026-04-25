"""E2E tests for the standard workflow (plan → confirm → implement → gate).

Verifies the plan-first confirmation flow, artifact creation, and the
pause-on-rejection path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.artifacts import load_phase_output
from devflow.core.console import console
from devflow.core.models import FeatureStatus
from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_build_loop
from devflow.orchestration.lifecycle import start_build


@pytest.mark.e2e
class TestStandardWorkflow:
    def test_feature_reaches_done_after_confirmation(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        confirm_plan: None,
    ) -> None:
        feature = start_build("add subtract function", "standard", mini_python)
        result = execute_build_loop(feature, base=mini_python)

        assert result is True
        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.status == FeatureStatus.DONE

    def test_planning_artifact_saved(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        confirm_plan: None,
    ) -> None:
        feature = start_build("add subtract function", "standard", mini_python)
        execute_build_loop(feature, base=mini_python)

        content = load_phase_output(feature.id, "planning", mini_python)
        assert content, "Planning artifact was not saved"
        assert "subtract" in content.lower()

    def test_plan_rejected_returns_false(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        callbacks_with_ui_confirm: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(console, "input", lambda _: "n")

        feature = start_build("add subtract function", "standard", mini_python)
        result = execute_build_loop(
            feature, base=mini_python, callbacks=callbacks_with_ui_confirm,  # type: ignore[arg-type]
        )

        assert result is False

    def test_plan_rejected_feature_not_done(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        callbacks_with_ui_confirm: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(console, "input", lambda _: "n")

        feature = start_build("add subtract function", "standard", mini_python)
        execute_build_loop(
            feature, base=mini_python, callbacks=callbacks_with_ui_confirm,  # type: ignore[arg-type]
        )

        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.status != FeatureStatus.DONE

    def test_plan_rejected_does_not_create_orphan_branch(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        callbacks_with_ui_confirm: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Rejecting the plan must NOT leave an orphan feat/* branch behind.

        Regression: previously the build loop created the branch upfront,
        so a rejection left an empty branch (0 commits) that the user had
        to clean up by hand.
        """
        import subprocess

        from devflow.integrations.git import branch_name

        monkeypatch.setattr(console, "input", lambda _: "n")

        feature = start_build("add subtract function", "standard", mini_python)
        execute_build_loop(
            feature, base=mini_python, callbacks=callbacks_with_ui_confirm,  # type: ignore[arg-type]
        )

        # The feature branch must not exist locally — rejection happens
        # *before* branch creation.
        branch = branch_name(feature.id)
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", branch],
            cwd=mini_python, capture_output=True,
        )
        assert result.returncode != 0, (
            f"Orphan branch {branch} was created despite plan rejection"
        )

    def test_resume_with_feedback_reruns_planning(
        self,
        mini_python: Path,
        mock_claude: None,
        no_github: None,
        callbacks_with_ui_confirm: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject plan → resume with feedback → planning reruns → feature completes."""
        from devflow.orchestration.lifecycle import resume_build

        # First build: reject the plan.
        monkeypatch.setattr(console, "input", lambda _: "n")
        feature = start_build("add subtract function", "standard", mini_python)
        execute_build_loop(
            feature, base=mini_python, callbacks=callbacks_with_ui_confirm,  # type: ignore[arg-type]
        )

        # Resume with feedback: planning will rerun (mock returns same output).
        # Switch confirm_plan back on.
        monkeypatch.setattr(console, "input", lambda _: "y")
        resumed = resume_build(feature.id, mini_python)
        assert resumed is not None

        result = execute_build_loop(
            resumed, feedback="please add tests too", base=mini_python,
            callbacks=callbacks_with_ui_confirm,  # type: ignore[arg-type]
        )
        assert result is True

        state = load_state(mini_python)
        f = state.get_feature(feature.id)
        assert f is not None
        assert f.status == FeatureStatus.DONE
