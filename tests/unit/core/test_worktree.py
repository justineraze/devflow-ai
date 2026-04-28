"""Tests for worktree support — metadata, concurrent state writes, stress."""

from __future__ import annotations

import threading
from pathlib import Path

from devflow.core.workflow import load_state, mutate_feature
from devflow.orchestration.lifecycle import start_build


class TestWorktreeMetadata:
    def test_worktree_path_defaults_to_none(self, tmp_path: Path) -> None:
        feature = start_build("test", "quick", tmp_path)
        assert feature.metadata.worktree_path is None

    def test_worktree_path_persists_in_state(self, tmp_path: Path) -> None:
        feature = start_build("test", "quick", tmp_path)
        with mutate_feature(feature.id, tmp_path) as feat:
            assert feat is not None
            feat.metadata.worktree_path = "/tmp/wt/test"
        state = load_state(tmp_path)
        tracked = state.get_feature(feature.id)
        assert tracked is not None
        assert tracked.metadata.worktree_path == "/tmp/wt/test"

    def test_worktree_path_cleared_on_none(self, tmp_path: Path) -> None:
        feature = start_build("test", "quick", tmp_path)
        with mutate_feature(feature.id, tmp_path) as feat:
            assert feat is not None
            feat.metadata.worktree_path = "/tmp/wt/test"
        with mutate_feature(feature.id, tmp_path) as feat:
            assert feat is not None
            feat.metadata.worktree_path = None
        state = load_state(tmp_path)
        tracked = state.get_feature(feature.id)
        assert tracked is not None
        assert tracked.metadata.worktree_path is None


class TestConcurrentStateWrites:
    def test_two_writers_dont_corrupt(self, tmp_path: Path) -> None:
        """Two threads writing simultaneously don't corrupt state.json."""
        f1 = start_build("feature one", "quick", tmp_path)
        f2 = start_build("feature two", "quick", tmp_path)

        errors: list[Exception] = []

        def writer(feature_id: str, value: str) -> None:
            try:
                with mutate_feature(feature_id, tmp_path) as feat:
                    if feat:
                        feat.metadata.feedback = value
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=writer, args=(f1.id, "feedback-1"))
        t2 = threading.Thread(target=writer, args=(f2.id, "feedback-2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        state = load_state(tmp_path)
        assert state.get_feature(f1.id) is not None
        assert state.get_feature(f2.id) is not None
        assert state.get_feature(f1.id).metadata.feedback == "feedback-1"
        assert state.get_feature(f2.id).metadata.feedback == "feedback-2"


class TestConcurrentStateStress:
    def test_three_writers_ten_iterations(self, tmp_path: Path) -> None:
        """3 threads × 10 iterations → zero corruption, all features present."""
        features = [
            start_build(f"stress feature {i}", "quick", tmp_path)
            for i in range(3)
        ]

        errors: list[Exception] = []

        def writer(feature_id: str, iterations: int) -> None:
            for i in range(iterations):
                try:
                    with mutate_feature(feature_id, tmp_path) as feat:
                        if feat:
                            feat.metadata.feedback = f"iter-{i}"
                except Exception as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(f.id, 10))
            for f in features
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent writes produced errors: {errors}"

        state = load_state(tmp_path)
        for f in features:
            tracked = state.get_feature(f.id)
            assert tracked is not None, f"Feature {f.id} missing after stress test"
            assert tracked.metadata.feedback == "iter-9"
