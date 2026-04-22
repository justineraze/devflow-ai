"""Tests for devflow.integrations.gate.secrets — scan_secrets."""

from pathlib import Path

import pytest

from devflow.integrations.gate.secrets import scan_secrets


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

    def test_detects_github_token(self, tmp_path: Path) -> None:
        """ghp_ token (36+ alphanumeric after prefix) is flagged."""
        (tmp_path / "ci.py").write_text("token = 'ghp_" + "a" * 40 + "'")
        result = scan_secrets(tmp_path)
        assert result.passed is False

    def test_detects_anthropic_key(self, tmp_path: Path) -> None:
        """sk-ant- key is flagged and the Anthropic-specific pattern matches."""
        (tmp_path / "client.py").write_text("key = 'sk-ant-" + "x" * 30 + "'")
        result = scan_secrets(tmp_path)
        assert result.passed is False
        assert "Anthropic" in result.details

    def test_detects_slack_token(self, tmp_path: Path) -> None:
        """xoxb- Slack bot token is flagged."""
        (tmp_path / "bot.py").write_text("token = 'xoxb-" + "a" * 20 + "'")
        result = scan_secrets(tmp_path)
        assert result.passed is False

    @pytest.mark.parametrize(
        "skip_dir",
        [".venv", "node_modules", "__pycache__", ".ruff_cache", ".devflow", "assets"],
    )
    def test_skips_configured_dirs(self, tmp_path: Path, skip_dir: str) -> None:
        """Secrets inside skip directories are not reported."""
        d = tmp_path / skip_dir
        d.mkdir()
        (d / "secret.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"')
        result = scan_secrets(tmp_path)
        assert result.passed is True, f"Should skip {skip_dir!r}"

    def test_skips_lock_and_whl(self, tmp_path: Path) -> None:
        """Lock files and wheel archives are not scanned."""
        (tmp_path / "poetry.lock").write_text('secret = "AKIAIOSFODNN7EXAMPLE"')
        (tmp_path / "pkg.whl").write_text("AKIAIOSFODNN7EXAMPLE")
        result = scan_secrets(tmp_path)
        assert result.passed is True

    def test_truncates_findings_to_20(self, tmp_path: Path) -> None:
        """Only the first 20 findings appear in details; total count is in message."""
        for i in range(25):
            # Each file contains a unique AWS key → 1 finding per file.
            key = f"AKIA{'ABCDEFGHIJ'[i % 10]}" + f"{i:016d}"[:16]
            (tmp_path / f"file_{i:02d}.py").write_text(f'key = "{key}"')
        result = scan_secrets(tmp_path)
        assert result.passed is False
        assert "25" in result.message
        assert len(result.details.split("\n")) == 20

    def test_unreadable_file_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OSError when reading a file is silently skipped, not raised."""
        (tmp_path / "unreadable.py").write_text("harmless")

        def _raise_oserror(*args: object, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _raise_oserror)
        result = scan_secrets(tmp_path)
        assert result.passed is True
