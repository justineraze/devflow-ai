"""Tests for devflow.integrations.gate.context — GateContext + build_context."""

from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.integrations.gate.context import GateContext, build_context


class TestGateContext:
    """Tests for the GateContext dataclass."""

    def test_audit_mode_defaults(self) -> None:
        ctx = GateContext(mode="audit")
        assert ctx.mode == "audit"
        assert ctx.changed_files == []
        assert ctx.base_sha == ""
        assert ctx.exclude_patterns == []

    def test_build_mode_with_files(self) -> None:
        files = [Path("src/app.py"), Path("src/utils.py")]
        ctx = GateContext(mode="build", changed_files=files, base_sha="abc123")
        assert ctx.mode == "build"
        assert len(ctx.changed_files) == 2
        assert ctx.base_sha == "abc123"

    def test_is_excluded_matches_glob(self) -> None:
        ctx = GateContext(mode="build", exclude_patterns=["wp-admin/**", "*.min.js"])
        assert ctx.is_excluded("wp-admin/index.php") is True
        assert ctx.is_excluded("wp-admin/css/style.css") is True
        assert ctx.is_excluded("bundle.min.js") is True
        assert ctx.is_excluded("src/app.py") is False

    def test_is_excluded_no_patterns(self) -> None:
        ctx = GateContext(mode="build")
        assert ctx.is_excluded("anything.py") is False

    def test_scoped_files_build_mode(self) -> None:
        ctx = GateContext(
            mode="build",
            changed_files=[Path("src/app.py"), Path("wp-admin/x.php")],
            exclude_patterns=["wp-admin/**"],
        )
        result = ctx.scoped_files(Path("/project"))
        assert result == [Path("src/app.py")]

    def test_scoped_files_audit_mode_returns_empty(self) -> None:
        ctx = GateContext(mode="audit")
        result = ctx.scoped_files(Path("/project"))
        assert result == []


class TestBuildContext:
    """Tests for the build_context factory function."""

    @patch("devflow.core.config.load_config")
    def test_audit_mode(self, mock_config, tmp_path: Path) -> None:
        from devflow.core.config import DevflowConfig
        mock_config.return_value = DevflowConfig()

        ctx = build_context(mode="audit", base=tmp_path)
        assert ctx.mode == "audit"
        assert ctx.changed_files == []
        assert ctx.exclude_patterns == []

    @patch("devflow.integrations.gate.context._git_diff_files")
    @patch("devflow.core.config.load_config")
    def test_build_mode_with_sha(self, mock_config, mock_diff, tmp_path: Path) -> None:
        from devflow.core.config import DevflowConfig, GateConfig
        mock_config.return_value = DevflowConfig(
            gate=GateConfig(exclude=["dist/**"]),
        )
        mock_diff.return_value = [Path("src/app.py"), Path("dist/bundle.js")]

        ctx = build_context(mode="build", base_sha="abc123", base=tmp_path)
        assert ctx.mode == "build"
        assert ctx.base_sha == "abc123"
        assert ctx.changed_files == [Path("src/app.py"), Path("dist/bundle.js")]
        assert ctx.exclude_patterns == ["dist/**"]

    @patch("devflow.core.config.load_config")
    def test_build_mode_no_sha_gives_empty_files(self, mock_config, tmp_path: Path) -> None:
        from devflow.core.config import DevflowConfig
        mock_config.return_value = DevflowConfig()

        ctx = build_context(mode="build", base_sha="", base=tmp_path)
        assert ctx.changed_files == []

    @patch("devflow.core.config.load_config")
    def test_exclude_from_config(self, mock_config, tmp_path: Path) -> None:
        from devflow.core.config import DevflowConfig, GateConfig
        mock_config.return_value = DevflowConfig(
            gate=GateConfig(exclude=["wp-admin/**", "*.sql"]),
        )

        ctx = build_context(mode="audit", base=tmp_path)
        assert ctx.exclude_patterns == ["wp-admin/**", "*.sql"]
