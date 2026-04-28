"""Tests for collect_phase_result and _parse_log_numstat."""

from devflow.core.metrics import PhaseMetrics, PhaseResult
from devflow.orchestration.phase_artifacts import _parse_log_numstat, collect_phase_result


class TestParseLogNumstat:
    def test_single_commit(self) -> None:
        raw = (
            "abc1234567890\x00feat: add login\n"
            "10\t2\tsrc/auth.py\n"
            "5\t0\ttests/test_auth.py\n"
        )
        commits = _parse_log_numstat(raw)
        assert len(commits) == 1
        assert commits[0].sha == "abc1234"
        assert commits[0].message == "feat: add login"
        assert commits[0].files == ["src/auth.py", "tests/test_auth.py"]
        assert commits[0].insertions == 15
        assert commits[0].deletions == 2

    def test_multiple_commits(self) -> None:
        raw = (
            "aaa1111111111\x00feat: first\n"
            "5\t1\tsrc/a.py\n"
            "\n"
            "bbb2222222222\x00fix: second\n"
            "3\t0\tsrc/b.py\n"
        )
        commits = _parse_log_numstat(raw)
        assert len(commits) == 2
        assert commits[0].message == "feat: first"
        assert commits[1].message == "fix: second"
        assert commits[0].insertions == 5
        assert commits[1].insertions == 3

    def test_empty_output(self) -> None:
        assert _parse_log_numstat("") == []
        assert _parse_log_numstat("\n") == []

    def test_binary_files_dashes(self) -> None:
        raw = (
            "abc1234567890\x00chore: add image\n"
            "-\t-\tassets/logo.png\n"
            "2\t0\tREADME.md\n"
        )
        commits = _parse_log_numstat(raw)
        assert len(commits) == 1
        assert commits[0].insertions == 2
        assert commits[0].deletions == 0
        assert "assets/logo.png" in commits[0].files

    def test_sha_truncated_to_7(self) -> None:
        raw = "abcdef1234567890abcdef1234567890abcdef12\x00msg\n"
        commits = _parse_log_numstat(raw)
        assert commits[0].sha == "abcdef1"

    def test_commit_with_no_files(self) -> None:
        raw = "abc1234567890\x00chore: empty commit\n"
        commits = _parse_log_numstat(raw)
        assert len(commits) == 1
        assert commits[0].files == []
        assert commits[0].insertions == 0


class TestCollectPhaseResultGraceful:
    """Test collect_phase_result when git is unavailable (no repo)."""

    def test_returns_empty_on_no_repo(self, tmp_path) -> None:
        metrics = PhaseMetrics()
        result = collect_phase_result("deadbeef", True, "output", metrics)
        assert isinstance(result, PhaseResult)
        assert result.commits == []
        assert result.success is True
        assert result.output == "output"
        assert result.metrics is metrics

    def test_preserves_success_flag(self, tmp_path) -> None:
        result = collect_phase_result("deadbeef", False, "fail", PhaseMetrics())
        assert result.success is False
