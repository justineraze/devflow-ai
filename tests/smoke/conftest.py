"""Shared fixtures for smoke tests.

Smoke tests call the real claude -p CLI.  They are slow (1–5 min each),
cost API tokens, and are non-deterministic.  Run them manually before a
release or when suspecting a prompt regression:

    uv run pytest -m smoke -v

Requirements:
    - Claude Code CLI installed and authenticated
    - No GitHub connection needed (push_and_create_pr is stubbed)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "e2e" / "fixtures" / "mini_python"


@pytest.fixture
def mini_python_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real git repo + devflow state, no mock on claude -p.

    Sets CWD so git.py's Path.cwd() calls hit the right repo.
    Stubs push_and_create_pr so no GitHub connection is needed.
    """
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_DIR, project)

    subprocess.run(["git", "init", "-b", "main"], cwd=project, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@devflow.ai"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Devflow Test"],
        cwd=project, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=project, capture_output=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial project"],
        cwd=project, capture_output=True,
    )

    monkeypatch.chdir(project)

    from devflow.core.config import DevflowConfig, save_config
    save_config(DevflowConfig(stack="python"), project)

    monkeypatch.setattr(
        "devflow.integrations.git.push_and_create_pr",
        lambda feature, branch, exclude=None: "https://github.com/test/repo/pull/1",
    )

    return project
