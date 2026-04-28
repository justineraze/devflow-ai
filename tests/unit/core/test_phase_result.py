"""Tests for CommitInfo and PhaseResult dataclasses."""

from devflow.core.metrics import CommitInfo, PhaseMetrics, PhaseResult


class TestCommitInfo:
    def test_defaults(self) -> None:
        c = CommitInfo(sha="abc1234", message="feat: hello")
        assert c.files == []
        assert c.insertions == 0
        assert c.deletions == 0

    def test_with_stats(self) -> None:
        c = CommitInfo(
            sha="abc1234", message="fix: bug",
            files=["a.py", "b.py"], insertions=10, deletions=3,
        )
        assert len(c.files) == 2
        assert c.insertions == 10
        assert c.deletions == 3


class TestPhaseResult:
    def test_defaults(self) -> None:
        r = PhaseResult(success=True, output="ok", metrics=PhaseMetrics())
        assert r.commits == []
        assert r.files_changed == []
        assert r.uncommitted_changes is False

    def test_with_commits(self) -> None:
        commits = [
            CommitInfo(sha="aaa", message="a", insertions=5),
            CommitInfo(sha="bbb", message="b", insertions=10),
        ]
        r = PhaseResult(
            success=True, output="done", metrics=PhaseMetrics(),
            commits=commits, files_changed=["x.py"],
        )
        assert len(r.commits) == 2
        assert r.files_changed == ["x.py"]

    def test_uncommitted_flag(self) -> None:
        r = PhaseResult(
            success=True, output="", metrics=PhaseMetrics(),
            uncommitted_changes=True,
        )
        assert r.uncommitted_changes is True
