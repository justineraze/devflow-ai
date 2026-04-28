"""Tests for user hooks."""

from __future__ import annotations

import stat
from pathlib import Path

from devflow.hooks import run_hook


def _create_hook(root: Path, name: str, content: str) -> Path:
    """Create a hook script."""
    hooks_dir = root / ".devflow" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / f"{name}.sh"
    hook.write_text(content)
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return hook


class TestRunHook:
    def test_missing_returns_true(self, tmp_path: Path) -> None:
        """Missing hook = success (no-op)."""
        assert run_hook("pre-build", cwd=tmp_path) is True

    def test_success(self, tmp_path: Path) -> None:
        """Hook exits 0 = success."""
        _create_hook(tmp_path, "pre-build", "#!/bin/sh\nexit 0\n")
        assert run_hook("pre-build", cwd=tmp_path) is True

    def test_failure(self, tmp_path: Path) -> None:
        """Hook exits non-0 = failure."""
        _create_hook(tmp_path, "pre-build", "#!/bin/sh\nexit 1\n")
        assert run_hook("pre-build", cwd=tmp_path) is False

    def test_with_args(self, tmp_path: Path) -> None:
        """Hook receives arguments."""
        marker = tmp_path / "marker.txt"
        _create_hook(
            tmp_path,
            "post-gate",
            f'#!/bin/sh\necho "$1" > "{marker}"\nexit 0\n',
        )
        assert run_hook("post-gate", "passed", cwd=tmp_path) is True
        assert marker.read_text().strip() == "passed"

    def test_nonexistent_dir_returns_true(self, tmp_path: Path) -> None:
        """No .devflow/hooks dir at all = success (no-op)."""
        assert run_hook("on-failure", cwd=tmp_path) is True

    def test_multiple_args(self, tmp_path: Path) -> None:
        """Hook receives multiple arguments."""
        marker = tmp_path / "args.txt"
        _create_hook(
            tmp_path,
            "on-failure",
            f'#!/bin/sh\necho "$1 $2" > "{marker}"\nexit 0\n',
        )
        assert run_hook("on-failure", "implementing", "error msg", cwd=tmp_path) is True
        assert marker.read_text().strip() == "implementing error msg"
