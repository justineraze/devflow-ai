"""Tests for devflow.core.registry — unified backend/tracker registry."""

from __future__ import annotations

import pytest

from devflow.core.registry import (
    clear_registry,
    get_backend,
    get_tracker,
    list_backends,
    list_trackers,
    register_backend,
    register_tracker,
    set_active_backend,
    set_active_tracker,
)
from devflow.core.state_machine import FeatureStatus

# ── Fixtures ─────────────────────────────────────────────────────────


class _FakeBackend:
    @property
    def name(self) -> str:
        return "fake"

    def model_name(self, tier: object) -> str:
        return "fake-model"

    def execute(self, **kwargs: object) -> tuple[bool, str, object]:
        return True, "", object()

    def one_shot(self, **kwargs: object) -> str | None:
        return None

    def check_available(self) -> tuple[bool, str]:
        return True, "fake"


class _FakeTracker:
    @property
    def name(self) -> str:
        return "fake"

    def check_available(self) -> tuple[bool, str]:
        return True, "ok"

    def create_issue(
        self, *, title: str, description: str, parent_id: str | None = None,
    ) -> str:
        return "FAKE-1"

    def update_status(self, *, issue_id: str, status: FeatureStatus) -> None:
        pass

    def link_pr(self, *, issue_id: str, pr_url: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    clear_registry()


# ── Backend tests ────────────────────────────────────────────────────


class TestBackendRegistry:
    def test_get_backend_raises_when_empty(self) -> None:
        with pytest.raises(RuntimeError, match="No backend registered"):
            get_backend()

    def test_register_and_get(self) -> None:
        backend = _FakeBackend()
        register_backend("fake", backend)
        set_active_backend("fake")
        assert get_backend() is backend

    def test_get_by_name(self) -> None:
        backend = _FakeBackend()
        register_backend("fake", backend)
        set_active_backend("fake")
        assert get_backend("fake") is backend

    def test_get_unknown_raises(self) -> None:
        register_backend("fake", _FakeBackend())
        set_active_backend("fake")
        with pytest.raises(RuntimeError, match="Unknown backend"):
            get_backend("unknown")

    def test_set_active_unknown_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Cannot activate unknown"):
            set_active_backend("nope")

    def test_list_backends(self) -> None:
        register_backend("b", _FakeBackend())
        register_backend("a", _FakeBackend())
        assert list_backends() == ["a", "b"]


# ── Tracker tests ────────────────────────────────────────────────────


class TestTrackerRegistry:
    def test_get_tracker_returns_none_when_empty(self) -> None:
        assert get_tracker() is None

    def test_register_and_get(self) -> None:
        tracker = _FakeTracker()
        register_tracker("fake", tracker)
        set_active_tracker("fake")
        assert get_tracker() is tracker

    def test_get_by_name(self) -> None:
        tracker = _FakeTracker()
        register_tracker("fake", tracker)
        assert get_tracker("fake") is tracker

    def test_get_unknown_returns_none(self) -> None:
        assert get_tracker("unknown") is None

    def test_set_active_unknown_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Unknown tracker"):
            set_active_tracker("nope")

    def test_list_trackers(self) -> None:
        register_tracker("b", _FakeTracker())
        register_tracker("a", _FakeTracker())
        assert list_trackers() == ["a", "b"]


# ── Clear ────────────────────────────────────────────────────────────


class TestClearRegistry:
    def test_clear_resets_everything(self) -> None:
        register_backend("x", _FakeBackend())
        set_active_backend("x")
        register_tracker("y", _FakeTracker())
        set_active_tracker("y")

        clear_registry()

        with pytest.raises(RuntimeError):
            get_backend()
        assert get_tracker() is None
        assert list_backends() == []
        assert list_trackers() == []
