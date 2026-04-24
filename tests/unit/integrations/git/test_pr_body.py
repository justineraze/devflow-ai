"""Tests for devflow.integrations.git.pr_body — PR body and push orchestration."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.models import Feature, FeatureStatus
from devflow.integrations.git.pr_body import (
    build_pr_body,
    parse_plan_changes,
    parse_plan_summary,
    push_and_create_pr,
)

_SAMPLE_PLAN = """\
## Plan: feat-gate-parallel-0415 — Run ruff and pytest in parallel in the gate

### Scope
- Type: extension
- Complexity: low
- Estimated steps: 3
- Module: gate

### Affected files
| File | Action | What changes |
|------|--------|-------------|
| src/devflow/integrations/gate.py | modify | parallel execution |

### Quality audit
No issues found.

### Implementation steps
1. **src/devflow/integrations/gate.py** — wrap runners with `asyncio.gather`.
   Test: test_gate_runs_in_parallel asserts both checks complete
2. **tests/integrations/test_gate.py** — add fixture with two slow checks.
   Test: wall time < sum of individual times
3. **src/devflow/ui/rendering.py** — update gate panel to show parallel badge.
   Test: snapshot test

### Risks
- asyncio loop already running → use thread executor as fallback
"""


class TestParsePlanSummary:
    def test_extracts_summary_with_em_dash(self) -> None:
        assert parse_plan_summary(_SAMPLE_PLAN) == (
            "Run ruff and pytest in parallel in the gate"
        )

    def test_extracts_summary_with_en_dash(self) -> None:
        plan = "## Plan: feat-xxx – My feature summary\n### Scope"
        assert parse_plan_summary(plan) == "My feature summary"

    def test_extracts_summary_with_hyphen(self) -> None:
        plan = "## Plan: feat-xxx - Simple fix\n### Scope"
        assert parse_plan_summary(plan) == "Simple fix"

    def test_returns_empty_when_no_header(self) -> None:
        assert parse_plan_summary("No plan header here") == ""

    def test_returns_empty_on_empty_string(self) -> None:
        assert parse_plan_summary("") == ""

    def test_does_not_match_hyphen_inside_summary_words(self) -> None:
        # Regression: "re-inject" was eaten by the greedy [—–\-] match,
        # returning only "inject devflow context" instead of the full summary.
        plan = "## Plan: feat-xxx — PostCompact hook: re-inject devflow context\n### Scope"
        assert parse_plan_summary(plan) == "PostCompact hook: re-inject devflow context"

    def test_does_not_match_hyphens_in_feature_id(self) -> None:
        # The feature ID itself contains hyphens — separator must be the dash
        # between ID and summary, not a hyphen inside the ID.
        plan = "## Plan: feat-add-caching-layer-0415 — Add Redis caching\n### Scope"
        assert parse_plan_summary(plan) == "Add Redis caching"


class TestParsePlanChanges:
    def test_extracts_numbered_steps_as_bullets(self) -> None:
        result = parse_plan_changes(_SAMPLE_PLAN)
        lines = result.splitlines()
        assert len(lines) == 3
        assert all(line.startswith("- ") for line in lines)

    def test_strips_test_tail(self) -> None:
        result = parse_plan_changes(_SAMPLE_PLAN)
        assert "Test:" not in result

    def test_respects_max_items(self) -> None:
        result = parse_plan_changes(_SAMPLE_PLAN, max_items=2)
        assert len(result.splitlines()) == 2

    def test_returns_empty_when_section_absent(self) -> None:
        plan = "## Plan: feat-xxx — Something\n### Scope\nno steps here"
        assert parse_plan_changes(plan) == ""

    def test_first_bullet_contains_file_and_action(self) -> None:
        result = parse_plan_changes(_SAMPLE_PLAN)
        first = result.splitlines()[0]
        assert "gate.py" in first
        assert "asyncio.gather" in first


class TestBuildPrBody:
    def _make_feature(
        self,
        tmp_path: Path,
        plan_output: str = "",
        gate_output: str = "",
    ) -> Feature:
        from devflow.core.artifacts import save_phase_output

        feature = Feature(
            id="feat-test-0415",
            description="raw user prompt",
            workflow="standard",
        )
        if plan_output:
            save_phase_output(feature.id, "planning", plan_output, tmp_path)
        if gate_output:
            save_phase_output(feature.id, "gate", gate_output, tmp_path)
        return feature

    def test_summary_from_plan_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path, plan_output=_SAMPLE_PLAN)
        body = build_pr_body(feature)
        assert "Run ruff and pytest in parallel in the gate" in body

    def test_changes_section_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path, plan_output=_SAMPLE_PLAN)
        body = build_pr_body(feature)
        assert "## Changes" in body
        assert "gate.py" in body

    def test_fallback_to_description_when_no_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path)
        body = build_pr_body(feature)
        assert "raw user prompt" in body
        assert "## Changes" not in body

    def test_gate_output_included(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(
            tmp_path, plan_output=_SAMPLE_PLAN, gate_output="✓ ruff passed\n✓ pytest 42 tests"
        )
        body = build_pr_body(feature)
        assert "## Quality gate" in body
        assert "ruff passed" in body

    def test_plan_output_not_dumped_raw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path, plan_output=_SAMPLE_PLAN)
        body = build_pr_body(feature)
        # The raw plan sections should NOT appear in the PR body.
        assert "### Implementation steps" not in body
        assert "### Affected files" not in body

    def test_footer_always_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path)
        body = build_pr_body(feature)
        assert "devflow-ai" in body


class TestPushAndCreatePr:
    @patch("devflow.integrations.git.smart_messages._call_one_shot", return_value=None)
    @patch("devflow.integrations.git.smart_messages._get_staged_diff", return_value="")
    @patch("devflow.integrations.git.repo.subprocess.run")
    def test_uses_conventional_commit_title(
        self, mock_run: MagicMock, mock_diff: MagicMock, mock_haiku: MagicMock,
    ) -> None:
        feature = Feature(
            id="feat-test-001", description="Add auth",
            workflow="standard", status=FeatureStatus.DONE, phases=[],
        )
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=1),  # git diff --cached --quiet (has changes)
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0, stdout="1\n"),  # rev-list --count
            MagicMock(returncode=0),  # git push
            MagicMock(returncode=0, stdout="0\t0\t\n"),  # git diff --numstat (branch diff)
            MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # gh pr create
        ]

        url = push_and_create_pr(feature, "feat/feat-test-001")
        assert url == "https://github.com/pr/1"

        commit_msg = mock_run.call_args_list[2][0][0][-1]
        assert commit_msg.startswith("feat:")

        pr_args = mock_run.call_args_list[6][0][0]
        title_idx = pr_args.index("--title") + 1
        assert pr_args[title_idx] == "feat: add auth"
