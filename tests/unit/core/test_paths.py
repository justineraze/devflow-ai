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
    """venv_env resolves: project .venv > $VIRTUAL_ENV > sys.executable."""

    def test_returns_copy_not_original(self) -> None:
        env = venv_env()
        assert env is not os.environ

    def test_prefers_project_venv(self, tmp_path: Path) -> None:
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        env = venv_env(tmp_path)
        assert env["PATH"].startswith(str(venv_bin))

    def test_falls_back_to_virtual_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        custom = tmp_path / "custom_venv"
        (custom / "bin").mkdir(parents=True)
        monkeypatch.setenv("VIRTUAL_ENV", str(custom))
        project = tmp_path / "project"
        project.mkdir()
        env = venv_env(project)
        assert str(custom / "bin") in env["PATH"]

    def test_falls_back_to_sys_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        project = tmp_path / "project"
        project.mkdir()
        env = venv_env(project)
        assert str(Path(sys.executable).parent) in env["PATH"]

    def test_default_root_is_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        env = venv_env()
        assert env["PATH"].startswith(str(venv_bin))

    # ------------------------------------------------------------------
    # Windows path handling — _VENV_BIN = "Scripts" on nt
    # ------------------------------------------------------------------

    def test_windows_uses_scripts_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On Windows (os.name == 'nt') the venv bin dir is 'Scripts'."""
        import devflow.core.paths as _paths_mod

        monkeypatch.setattr(_paths_mod, "_VENV_BIN", "Scripts")
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        env = venv_env(tmp_path)
        assert env["PATH"].startswith(str(scripts_dir))

    def test_posix_uses_bin_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On POSIX (os.name == 'posix') the venv bin dir is 'bin'."""
        import devflow.core.paths as _paths_mod

        monkeypatch.setattr(_paths_mod, "_VENV_BIN", "bin")
        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        env = venv_env(tmp_path)
        assert env["PATH"].startswith(str(bin_dir))

    def test_virtual_env_fallback_windows_uses_scripts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """VIRTUAL_ENV fallback also uses Scripts on Windows."""
        import devflow.core.paths as _paths_mod

        monkeypatch.setattr(_paths_mod, "_VENV_BIN", "Scripts")
        custom = tmp_path / "custom_venv"
        (custom / "Scripts").mkdir(parents=True)
        monkeypatch.setenv("VIRTUAL_ENV", str(custom))
        project = tmp_path / "project"
        project.mkdir()
        env = venv_env(project)
        assert str(custom / "Scripts") in env["PATH"]

    def test_preserves_existing_path(self) -> None:
        env = venv_env()
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if entry:
                assert entry in env["PATH"]

    def test_other_env_vars_copied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVFLOW_TEST_MARKER", "hello")
        env = venv_env()
        assert env["DEVFLOW_TEST_MARKER"] == "hello"


class TestVenvEnvUvToolInstallScenario:
    """Integration-style tests simulating 'devflow installed via uv tool install'.

    When devflow is installed globally with ``uv tool install devflow-ai`` its
    isolated tool-venv does **not** contain the target project's dev deps (ruff,
    pytest).  ``venv_env()`` must therefore resolve the project-local ``.venv``
    so that gate checks find the right executables.

    These tests use real subprocess calls against a tiny stub executable placed
    in a temporary ``.venv/bin`` directory, verifying the full PATH resolution
    chain end-to-end without needing an actual virtualenv.
    """

    def _make_stub(self, bin_dir: Path, name: str) -> Path:
        """Write a minimal executable stub that exits 0 and return its path."""
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        return stub

    def test_project_venv_used_over_system_path(self, tmp_path: Path) -> None:
        """A tool in project .venv/bin is found even if absent from system PATH."""
        import subprocess

        from devflow.core.paths import venv_env

        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        self._make_stub(bin_dir, "fake-tool-devflow-test")

        env = venv_env(tmp_path)
        # The project .venv/bin must appear first in PATH.
        assert env["PATH"].startswith(str(bin_dir))

        # The stub should be findable and runnable via the resolved env.
        result = subprocess.run(
            ["fake-tool-devflow-test"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0

    def test_gate_ruff_resolves_via_project_venv(self, tmp_path: Path) -> None:
        """_run_command_check finds a project-local stub even without a system ruff."""

        from devflow.integrations.gate.checks import _run_command_check

        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        stub_name = "ruff-devflow-stub"
        self._make_stub(bin_dir, stub_name)

        # Verify that the command succeeds (tool resolved from project venv)
        # rather than raising FileNotFoundError.
        result = _run_command_check(stub_name, [stub_name], cwd=tmp_path)
        assert result.passed is True
        assert not result.skipped, "tool should be found, not skipped"

    def test_no_project_venv_falls_back_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without .venv the env still contains a usable PATH (no crash)."""
        from devflow.core.paths import venv_env

        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        project = tmp_path / "no_venv_project"
        project.mkdir()

        env = venv_env(project)
        # PATH must exist and be non-empty for subprocess calls to work.
        assert "PATH" in env
        assert env["PATH"]


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
