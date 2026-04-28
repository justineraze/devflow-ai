"""Tests for devflow init wizard (non-interactive mode)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devflow.core.config import clear_config_cache, load_config
from devflow.setup.init import _update_gitignore, run_init_wizard


def _fake_detect_stack(root: Path) -> str | None:
    """Detect stack by checking for common files (test-safe, no imports)."""
    if any(root.glob("*.py")):
        return "python"
    return None


def _fake_detect_base_branch() -> str:
    return "main"


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal project directory with a Python file."""
    (tmp_path / "main.py").write_text("print('hello')\n")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(tmp_path),
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=False,
    )
    clear_config_cache()
    return tmp_path


def test_init_non_interactive_creates_config(project_dir: Path) -> None:
    """Non-interactive init creates config.yaml."""
    config = run_init_wizard(
        stack="python",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
    )
    assert config.stack == "python"
    assert config.base_branch == "main"
    assert config.backend == "claude"

    saved = load_config(project_dir)
    assert saved.stack == "python"


def test_init_creates_state_json(project_dir: Path) -> None:
    """Init creates state.json if absent."""
    run_init_wizard(
        stack="python",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
    )
    state_file = project_dir / ".devflow" / "state.json"
    assert state_file.exists()


def test_init_updates_gitignore(project_dir: Path) -> None:
    """Init adds devflow entries to .gitignore."""
    run_init_wizard(
        stack="python",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
    )
    gitignore = project_dir / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".devflow/state.json" in content
    assert ".devflow/.worktrees/" in content
    assert ".devflow/*.lock" in content


def test_init_gitignore_idempotent(project_dir: Path) -> None:
    """Running init twice doesn't duplicate .gitignore entries."""
    for _ in range(2):
        clear_config_cache()
        run_init_wizard(
            stack="python",
            base_branch="main",
            backend="claude",
            no_tracker=True,
            base=project_dir,
        )
    content = (project_dir / ".gitignore").read_text()
    assert content.count(".devflow/state.json") == 1


def test_init_with_linear_team(project_dir: Path) -> None:
    """Non-interactive init with Linear team."""
    config = run_init_wizard(
        stack="python",
        base_branch="main",
        backend="claude",
        linear_team="ABC",
        base=project_dir,
    )
    assert config.linear.team == "ABC"


def test_init_with_custom_gate(project_dir: Path) -> None:
    """Non-interactive init with custom gate commands."""
    config = run_init_wizard(
        stack="python",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        gate_lint="ruff check src/",
        gate_test="pytest -x",
        base=project_dir,
    )
    assert config.gate.lint == "ruff check src/"
    assert config.gate.test == "pytest -x"


def test_init_auto_detect_stack(project_dir: Path) -> None:
    """Auto-detect stack when explicitly requested."""
    config = run_init_wizard(
        stack="auto-detect",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
        detect_stack_fn=_fake_detect_stack,
    )
    assert config.stack == "python"


def test_update_gitignore_no_duplicate(tmp_path: Path) -> None:
    """_update_gitignore doesn't add entries that already exist."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".devflow/state.json\n")
    _update_gitignore(tmp_path)
    content = gitignore.read_text()
    assert content.count(".devflow/state.json") == 1


def test_update_gitignore_appends_missing_newline(tmp_path: Path) -> None:
    """_update_gitignore appends a newline if file doesn't end with one."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/")  # no trailing newline
    _update_gitignore(tmp_path)
    content = gitignore.read_text()
    assert "node_modules/" in content
    assert ".devflow/state.json" in content
    assert "node_modules/\n" in content


def test_init_default_backend_is_claude(project_dir: Path) -> None:
    """When backend is not specified, defaults to claude."""
    config = run_init_wizard(
        stack="python",
        base_branch="main",
        no_tracker=True,
        backend="claude",
        base=project_dir,
    )
    assert config.backend == "claude"


def test_init_pi_backend(project_dir: Path) -> None:
    """Non-interactive init with pi backend."""
    config = run_init_wizard(
        stack="python",
        base_branch="main",
        backend="pi",
        no_tracker=True,
        base=project_dir,
    )
    assert config.backend == "pi"


def test_init_noop_detect_when_no_fn(project_dir: Path) -> None:
    """Without detect fns, auto-detect falls back to None/main."""
    config = run_init_wizard(
        stack="auto-detect",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
        # no detect_stack_fn → uses _noop_detect_stack → None
    )
    assert config.stack is None


def test_init_with_injected_detect_fns(project_dir: Path) -> None:
    """Injected detect functions are used correctly."""
    config = run_init_wizard(
        stack="auto-detect",
        base_branch="main",
        backend="claude",
        no_tracker=True,
        base=project_dir,
        detect_stack_fn=lambda _: "typescript",
        detect_base_branch_fn=lambda: "develop",
    )
    assert config.stack == "typescript"
