"""Tests for devflow.core.paths — common path and environment helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from devflow.core.paths import (
    assets_dir,
    atomic_write_text,
    project_root,
    venv_env,
    workflows_dir,
)


class TestProjectLayout:
    """project_root / assets_dir / workflows_dir resolve bundled resources."""

    def test_project_root_exists(self) -> None:
        root = project_root()
        assert root.is_dir()

    def test_project_root_has_pyproject_or_assets(self) -> None:
        """Either the pyproject.toml or the assets dir identifies the root."""
        root = project_root()
        assert (root / "pyproject.toml").exists() or (root / "assets").is_dir()

    def test_assets_dir_exists(self) -> None:
        assert assets_dir().is_dir()

    def test_assets_dir_contains_agents(self) -> None:
        assert (assets_dir() / "agents").is_dir()

    def test_assets_dir_contains_skills(self) -> None:
        assert (assets_dir() / "skills").is_dir()

    def test_workflows_dir_exists(self) -> None:
        assert workflows_dir().is_dir()

    def test_workflows_dir_has_standard_yaml(self) -> None:
        assert (workflows_dir() / "standard.yaml").exists()


class TestVenvEnv:
    """venv_env prepends the active venv's bin dir to PATH."""

    def test_returns_copy_not_original(self) -> None:
        env = venv_env()
        assert env is not os.environ

    def test_path_is_prefixed_with_venv_bin(self) -> None:
        env = venv_env()
        venv_bin = str(Path(sys.executable).parent)
        assert env["PATH"].startswith(venv_bin + os.pathsep)

    def test_preserves_original_path(self) -> None:
        env = venv_env()
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if entry:
                assert entry in env["PATH"]

    def test_handles_empty_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PATH", raising=False)
        env = venv_env()
        venv_bin = str(Path(sys.executable).parent)
        # Ends with os.pathsep when original PATH was missing.
        assert env["PATH"].startswith(venv_bin)

    def test_other_env_vars_copied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVFLOW_TEST_MARKER", "hello")
        env = venv_env()
        assert env["DEVFLOW_TEST_MARKER"] == "hello"


class TestAtomicWriteText:
    """atomic_write_text writes via tmp + os.replace, cleaning up on failure."""

    def test_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "file.txt"
        atomic_write_text(target, "x")
        assert target.read_text() == "x"

    def test_no_tmp_file_remains(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "ok")
        # Nothing ending in .tmp should survive a successful write.
        assert not list(tmp_path.glob("*.tmp"))

    def test_cleans_up_tmp_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If os.replace raises, the temp file must be removed."""
        target = tmp_path / "out.txt"

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr("devflow.core.paths.os.replace", boom)
        with pytest.raises(OSError, match="replace failed"):
            atomic_write_text(target, "data")

        assert not list(tmp_path.glob("*.tmp"))
        assert not target.exists()
