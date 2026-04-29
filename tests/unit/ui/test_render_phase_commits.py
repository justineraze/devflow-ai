"""Tests for render_phase_commits in ui/rendering.py."""

from io import StringIO

from rich.console import Console

from devflow.core.metrics import CommitInfo, PhaseMetrics, PhaseResult


class TestRenderPhaseCommits:
    def _capture(self, phase_result: PhaseResult, phase_name: str = "implementing") -> str:
        import devflow.ui.rendering as mod

        buf = StringIO()
        original = mod.console
        mod.console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        try:
            mod.render_phase_commits(phase_name, phase_result)
        finally:
            mod.console = original
        return buf.getvalue()

    def test_single_commit(self) -> None:
        result = PhaseResult(
            success=True, output="", metrics=PhaseMetrics(),
            commits=[CommitInfo(
                sha="abc1234", message="feat: add login",
                files=["src/auth.py", "tests/test_auth.py"],
                insertions=34, deletions=2,
            )],
            files_changed=["src/auth.py", "tests/test_auth.py"],
        )
        output = self._capture(result)
        assert "abc1234" in output
        assert "feat: add login" in output
        assert "2 files changed" in output
        assert "34 insertion" in output

    def test_multiple_commits(self) -> None:
        result = PhaseResult(
            success=True, output="", metrics=PhaseMetrics(),
            commits=[
                CommitInfo(
                    sha="aaa1111", message="feat: first",
                    files=["a.py"], insertions=10, deletions=0,
                ),
                CommitInfo(
                    sha="bbb2222", message="fix: second",
                    files=["b.py", "c.py"], insertions=20, deletions=5,
                ),
            ],
            files_changed=["a.py", "b.py", "c.py"],
        )
        output = self._capture(result)
        assert "aaa1111" in output
        assert "bbb2222" in output
        assert "Total:" in output
        assert "30 insertion" in output

    def test_no_commits_no_changes(self) -> None:
        result = PhaseResult(
            success=True, output="", metrics=PhaseMetrics(),
            commits=[], files_changed=[],
        )
        output = self._capture(result)
        assert output.strip() == ""

    def test_planning_shows_step_count(self) -> None:
        result = PhaseResult(
            success=True,
            output="Plan:\n- Step 1\n- Step 2\n- Step 3\n",
            metrics=PhaseMetrics(),
        )
        output = self._capture(result, "planning")
        assert "3 steps" in output

    def test_reviewing_shows_verdict(self) -> None:
        result = PhaseResult(
            success=True,
            output="Verdict: APPROVE\nLooks good.",
            metrics=PhaseMetrics(),
        )
        output = self._capture(result, "reviewing")
        assert "APPROVED" in output

    def test_reviewing_shows_blocking_count(self) -> None:
        result = PhaseResult(
            success=True,
            output="Verdict: REQUEST_CHANGES\n- [BLOCKING] Fix X\n- [BLOCKING] Fix Y\n",
            metrics=PhaseMetrics(),
        )
        output = self._capture(result, "reviewing")
        assert "REQUEST_CHANGES" in output
        assert "2 blocking" in output

    def test_deletions_shown_in_single_commit(self) -> None:
        result = PhaseResult(
            success=True, output="", metrics=PhaseMetrics(),
            commits=[CommitInfo(
                sha="abc1234", message="refactor: clean",
                files=["x.py"], insertions=5, deletions=10,
            )],
            files_changed=["x.py"],
        )
        output = self._capture(result)
        assert "10 deletion" in output
