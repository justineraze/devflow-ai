"""Tests for devflow.gate — quality gate checks."""

from pathlib import Path

from devflow.gate import CheckResult, GateReport, scan_secrets


class TestCheckResult:
    def test_passed_check(self) -> None:
        result = CheckResult(name="test", passed=True, message="OK")
        assert result.passed is True

    def test_failed_check(self) -> None:
        result = CheckResult(name="test", passed=False, message="FAIL")
        assert result.passed is False


class TestGateReport:
    def test_all_passed(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=True))
        assert report.passed is True

    def test_one_failed(self) -> None:
        report = GateReport()
        report.add(CheckResult(name="a", passed=True))
        report.add(CheckResult(name="b", passed=False))
        assert report.passed is False

    def test_empty_report_passes(self) -> None:
        report = GateReport()
        assert report.passed is True


class TestScanSecrets:
    def test_clean_project(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')")
        result = scan_secrets(tmp_path)
        assert result.passed is True

    def test_detects_aws_key(self, tmp_path: Path) -> None:
        (tmp_path / "config.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is False
        assert "AWS" in result.message or "secret" in result.message.lower()

    def test_detects_private_key(self, tmp_path: Path) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----"
        (tmp_path / "key.pem").write_text(pem)
        result = scan_secrets(tmp_path)
        assert result.passed is False

    def test_detects_api_key(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("api_key: 'sk_live_abcdefghijklmnopqrstuvwx'")
        result = scan_secrets(tmp_path)
        assert result.passed is False

    def test_skips_binary_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_text('key = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is True

    def test_skips_git_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text('secret = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is True
