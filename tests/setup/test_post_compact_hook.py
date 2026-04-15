"""Integration tests for assets/hooks/devflow-post-compact.sh."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HOOK_PATH = (
    Path(__file__).resolve().parent.parent.parent / "assets" / "hooks" / "devflow-post-compact.sh"
)


def _run_hook(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute the hook script in *cwd*, returning the completed process."""
    return subprocess.run(
        ["bash", str(HOOK_PATH)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=10,
    )


def _make_state(tmp_path: Path, features: dict) -> None:
    """Write .devflow/state.json in *tmp_path*."""
    devflow = tmp_path / ".devflow"
    devflow.mkdir(parents=True, exist_ok=True)
    (devflow / "state.json").write_text(json.dumps({"version": 1, "features": features}))


class TestPostCompactHookNormal:
    def test_outputs_active_feature_and_phase(self, tmp_path: Path) -> None:
        features = {
            "f-001": {
                "id": "f-001",
                "description": "My cool feature",
                "current_phase": "implementing",
                "status": "in_progress",
                "updated_at": "2026-04-15T10:00:00",
            }
        }
        _make_state(tmp_path, features)

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert "f-001" in result.stdout
        assert "My cool feature" in result.stdout
        assert "implementing" in result.stdout
        assert "in_progress" in result.stdout
        assert "# devflow context (post-compact)" in result.stdout

    def test_includes_plan_summary(self, tmp_path: Path) -> None:
        features = {
            "f-002": {
                "id": "f-002",
                "description": "Feature with plan",
                "current_phase": "planning",
                "status": "pending",
                "updated_at": "2026-04-15T12:00:00",
            }
        }
        _make_state(tmp_path, features)

        # Create planning.md in .devflow/f-002/
        plan_dir = tmp_path / ".devflow" / "f-002"
        plan_dir.mkdir()
        (plan_dir / "planning.md").write_text("## Plan\nStep 1: do the thing\nStep 2: test it\n")

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert "Plan summary" in result.stdout
        assert "Step 1: do the thing" in result.stdout

    def test_plan_summary_limited_to_40_lines(self, tmp_path: Path) -> None:
        features = {
            "f-003": {
                "id": "f-003",
                "description": "Big plan",
                "current_phase": "planning",
                "status": "pending",
                "updated_at": "2026-04-15T12:00:00",
            }
        }
        _make_state(tmp_path, features)

        plan_dir = tmp_path / ".devflow" / "f-003"
        plan_dir.mkdir()
        lines = [f"Line {i}" for i in range(80)]
        (plan_dir / "planning.md").write_text("\n".join(lines))

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        # Line 40 (index 39) should appear, line 41 (index 40) should not.
        assert "Line 39" in result.stdout
        assert "Line 40" not in result.stdout

    def test_picks_most_recent_active_feature(self, tmp_path: Path) -> None:
        features = {
            "f-old": {
                "id": "f-old",
                "description": "Old feature",
                "current_phase": "implementing",
                "status": "in_progress",
                "updated_at": "2026-04-10T10:00:00",
            },
            "f-new": {
                "id": "f-new",
                "description": "New feature",
                "current_phase": "gate",
                "status": "in_progress",
                "updated_at": "2026-04-15T18:00:00",
            },
        }
        _make_state(tmp_path, features)

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert "f-new" in result.stdout
        assert "f-old" not in result.stdout


class TestPostCompactHookEdgeCases:
    def test_no_state_json_exits_silently(self, tmp_path: Path) -> None:
        result = _run_hook(tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_all_features_done_exits_silently(self, tmp_path: Path) -> None:
        features = {
            "f-done": {
                "id": "f-done",
                "description": "Finished",
                "current_phase": "gate",
                "status": "done",
                "updated_at": "2026-04-15T10:00:00",
            }
        }
        _make_state(tmp_path, features)

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_blocked_feature_ignored(self, tmp_path: Path) -> None:
        features = {
            "f-blocked": {
                "id": "f-blocked",
                "description": "Blocked work",
                "current_phase": "implementing",
                "status": "blocked",
                "updated_at": "2026-04-15T10:00:00",
            }
        }
        _make_state(tmp_path, features)

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_malformed_state_json_exits_silently(self, tmp_path: Path) -> None:
        devflow = tmp_path / ".devflow"
        devflow.mkdir()
        (devflow / "state.json").write_text("{not valid json!!!")

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_features_exits_silently(self, tmp_path: Path) -> None:
        _make_state(tmp_path, {})

        result = _run_hook(tmp_path)

        assert result.returncode == 0
        assert result.stdout.strip() == ""
