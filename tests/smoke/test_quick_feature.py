"""Smoke tests — full pipeline with real claude -p calls.

Each test calls devflow end-to-end on the mini_python fixture.
Tasks are intentionally trivial so Claude can implement them in 1-2 tool
calls and the gate passes without a fixing cycle.

Run manually before releases:
    uv run pytest -m smoke -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devflow.core.models import FeatureStatus
from devflow.core.workflow import load_state
from devflow.orchestration.build import execute_build_loop
from devflow.orchestration.lifecycle import start_build


@pytest.mark.smoke
def test_quick_add_function(
    mini_python_smoke: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude implements a trivial function; gate must pass; feature reaches DONE.

    This is the most critical smoke test — it catches:
    - Broken prompt construction
    - Broken claude -p invocation (timeout, bad args)
    - Gate regressions (ruff/pytest failures on generated code)
    - State machine regressions
    """
    feature = start_build(
        "add a subtract(a, b) function that returns a minus b",
        "quick",
        mini_python_smoke,
    )
    result = execute_build_loop(feature, base=mini_python_smoke)

    assert result is True, "Build did not succeed"

    state = load_state(mini_python_smoke)
    f = state.get_feature(feature.id)
    assert f is not None
    assert f.status == FeatureStatus.DONE

    # The function should exist somewhere in src/.
    src_code = "\n".join(
        p.read_text() for p in (mini_python_smoke / "src").glob("*.py")
    )
    assert "subtract" in src_code, (
        "Claude did not add the subtract function to src/"
    )


@pytest.mark.smoke
def test_quick_gate_passes_on_clean_code(
    mini_python_smoke: Path,
) -> None:
    """Gate alone on the untouched fixture must pass (baseline check).

    If this test fails, ruff or pytest has a problem with the fixture itself —
    fix the fixture before investigating generated code regressions.
    """
    from devflow.integrations.gate import run_gate

    report = run_gate(base=mini_python_smoke, stack="python")
    failed = [c for c in report.checks if not c.passed and not c.skipped]
    assert not failed, (
        "Baseline gate failed on the untouched fixture: "
        + ", ".join(f"{c.name}: {c.message}" for c in failed)
    )


@pytest.mark.smoke
def test_quick_build_creates_git_commit(
    mini_python_smoke: Path,
) -> None:
    """After a quick build, at least one commit must exist beyond the initial one."""
    import subprocess

    from devflow.orchestration.build import execute_build_loop
    from devflow.orchestration.lifecycle import start_build

    feature = start_build(
        "add a multiply(a, b) function that returns a times b",
        "quick",
        mini_python_smoke,
    )
    result = execute_build_loop(feature, base=mini_python_smoke)
    assert result is True

    log = subprocess.run(
        ["git", "log", "--oneline"],
        capture_output=True, text=True, cwd=mini_python_smoke,
    )
    commit_count = len(log.stdout.strip().splitlines())
    assert commit_count >= 2, (
        f"Expected at least 2 commits (initial + implementing), got {commit_count}"
    )
