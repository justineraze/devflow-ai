"""Tests for devflow.integrations.git — git operations."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.core.models import Feature, FeatureMetadata, FeatureStatus
from devflow.integrations.git import (
    _build_pr_body,
    _parse_plan_changes,
    _parse_plan_summary,
    branch_name,
    build_commit_message,
    build_pr_title,
    commit_changes,
    has_commits_ahead,
)


class TestBuildPrTitle:
    def test_feat_prefix_for_standard_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="Add user authentication",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add user authentication"

    def test_fix_prefix_for_quick_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="broken login redirect",
            workflow="quick",
        )
        assert build_pr_title(feature) == "fix: Broken login redirect"

    def test_strips_trailing_punctuation(self) -> None:
        feature = Feature(
            id="f-001", description="Add dark mode!",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add dark mode"

    def test_truncates_long_description(self) -> None:
        long = "Add a very long feature description that goes on and on and exceeds the limit"
        feature = Feature(id="f-001", description=long, workflow="standard")
        title = build_pr_title(feature)
        assert len(title) <= 70
        # Should break on word boundary.
        assert not title.endswith(" ")

    def test_preserves_acronyms(self) -> None:
        feature = Feature(
            id="f-001", description="Add OAuth support",
            workflow="standard",
        )
        assert build_pr_title(feature) == "feat: Add OAuth support"


class TestBuildCommitMessage:
    def test_no_suffix_matches_pr_title(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        assert build_commit_message(feature) == "feat: Add user auth"

    def test_with_phase_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "feat: Add user auth — implementing"

    def test_with_leftover_suffix(self) -> None:
        feature = Feature(
            id="f-001", description="Add user auth", workflow="standard",
        )
        msg = build_commit_message(feature, suffix="leftover changes")
        assert msg == "feat: Add user auth — leftover changes"

    def test_quick_workflow_uses_fix_prefix(self) -> None:
        feature = Feature(
            id="f-001", description="broken login", workflow="quick",
        )
        msg = build_commit_message(feature, suffix="implementing")
        assert msg == "fix: Broken login — implementing"

    def test_truncates_at_word_boundary(self) -> None:
        long = "Add something very long indeed going past the limit"
        feature = Feature(id="f-001", description=long, workflow="standard")
        msg = build_commit_message(feature, suffix="implementing")
        assert len(msg) <= 70
        assert not msg.endswith(" ")

    def test_with_scope(self) -> None:
        feature = Feature(
            id="f-001", description="Add caching layer", workflow="standard",
            metadata=FeatureMetadata(scope="runner"),
        )
        assert build_commit_message(feature) == "feat(runner): Add caching layer"

    def test_scope_in_fix_workflow(self) -> None:
        feature = Feature(
            id="f-001", description="broken login", workflow="quick",
            metadata=FeatureMetadata(scope="gate"),
        )
        assert build_commit_message(feature) == "fix(gate): Broken login"

    def test_no_scope_omits_parentheses(self) -> None:
        feature = Feature(id="f-001", description="Add user auth", workflow="standard")
        assert "(" not in build_commit_message(feature)


class TestBranchName:
    def test_strips_feat_prefix(self) -> None:
        assert branch_name("feat-add-caching-0415") == "feat/add-caching-0415"

    def test_no_prefix_preserved(self) -> None:
        assert branch_name("add-caching-0415") == "feat/add-caching-0415"

    def test_quick_fix_id(self) -> None:
        assert branch_name("feat-fix-login-1234") == "feat/fix-login-1234"


class TestCommitChanges:
    @patch("devflow.integrations.git.subprocess.run")
    def test_commits_when_changes_exist(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=1),  # git diff --cached --quiet (changes)
            MagicMock(returncode=0),  # git commit
        ]
        result = commit_changes("feat: test commit")
        assert result is True
        commit_call = mock_run.call_args_list[2]
        assert "feat: test commit" in commit_call[0][0]

    @patch("devflow.integrations.git.subprocess.run")
    def test_skips_when_nothing_to_commit(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=0),  # git diff --cached --quiet (clean)
        ]
        result = commit_changes("feat: nothing")
        assert result is False
        assert mock_run.call_count == 2


class TestHasCommitsAhead:
    @patch("devflow.integrations.git.subprocess.run")
    def test_has_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
        assert has_commits_ahead() is True

    @patch("devflow.integrations.git.subprocess.run")
    def test_no_commits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert has_commits_ahead() is False


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
        assert _parse_plan_summary(_SAMPLE_PLAN) == (
            "Run ruff and pytest in parallel in the gate"
        )

    def test_extracts_summary_with_en_dash(self) -> None:
        plan = "## Plan: feat-xxx – My feature summary\n### Scope"
        assert _parse_plan_summary(plan) == "My feature summary"

    def test_extracts_summary_with_hyphen(self) -> None:
        plan = "## Plan: feat-xxx - Simple fix\n### Scope"
        assert _parse_plan_summary(plan) == "Simple fix"

    def test_returns_empty_when_no_header(self) -> None:
        assert _parse_plan_summary("No plan header here") == ""

    def test_returns_empty_on_empty_string(self) -> None:
        assert _parse_plan_summary("") == ""


class TestParsePlanChanges:
    def test_extracts_numbered_steps_as_bullets(self) -> None:
        result = _parse_plan_changes(_SAMPLE_PLAN)
        lines = result.splitlines()
        assert len(lines) == 3
        assert all(line.startswith("- ") for line in lines)

    def test_strips_test_tail(self) -> None:
        result = _parse_plan_changes(_SAMPLE_PLAN)
        assert "Test:" not in result

    def test_respects_max_items(self) -> None:
        result = _parse_plan_changes(_SAMPLE_PLAN, max_items=2)
        assert len(result.splitlines()) == 2

    def test_returns_empty_when_section_absent(self) -> None:
        plan = "## Plan: feat-xxx — Something\n### Scope\nno steps here"
        assert _parse_plan_changes(plan) == ""

    def test_first_bullet_contains_file_and_action(self) -> None:
        result = _parse_plan_changes(_SAMPLE_PLAN)
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
        body = _build_pr_body(feature)
        assert "Run ruff and pytest in parallel in the gate" in body

    def test_changes_section_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path, plan_output=_SAMPLE_PLAN)
        body = _build_pr_body(feature)
        assert "## Changes" in body
        assert "gate.py" in body

    def test_fallback_to_description_when_no_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path)
        body = _build_pr_body(feature)
        assert "raw user prompt" in body
        assert "## Changes" not in body

    def test_gate_output_included(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(
            tmp_path, plan_output=_SAMPLE_PLAN, gate_output="✓ ruff passed\n✓ pytest 42 tests"
        )
        body = _build_pr_body(feature)
        assert "## Quality gate" in body
        assert "ruff passed" in body

    def test_plan_output_not_dumped_raw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path, plan_output=_SAMPLE_PLAN)
        body = _build_pr_body(feature)
        # The raw plan sections should NOT appear in the PR body.
        assert "### Implementation steps" not in body
        assert "### Affected files" not in body

    def test_footer_always_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        feature = self._make_feature(tmp_path)
        body = _build_pr_body(feature)
        assert "devflow-ai" in body


class TestPushAndCreatePr:
    @patch("devflow.integrations.git.subprocess.run")
    def test_uses_conventional_commit_title(self, mock_run: MagicMock) -> None:
        from devflow.integrations.git import push_and_create_pr

        feature = Feature(
            id="feat-test-001", description="Add auth",
            workflow="standard", status=FeatureStatus.DONE, phases=[],
        )
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -A
            MagicMock(returncode=1),  # git diff --cached --quiet (changes)
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0, stdout="1\n"),  # rev-list
            MagicMock(returncode=0),  # git push
            MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # gh pr
        ]
        url = push_and_create_pr(feature, "feat/feat-test-001")
        assert url == "https://github.com/pr/1"

        # Safety-net commit uses feat: prefix.
        commit_call = mock_run.call_args_list[2]
        commit_msg = commit_call[0][0][-1]
        assert commit_msg.startswith("feat:")

        # PR title uses Conventional Commits format.
        pr_call = mock_run.call_args_list[5]
        pr_args = pr_call[0][0]
        title_idx = pr_args.index("--title") + 1
        assert pr_args[title_idx] == "feat: Add auth"
