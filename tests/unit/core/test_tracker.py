"""Tests for devflow.core.tracker — IssueTracker Protocol."""

from __future__ import annotations

from devflow.core.state_machine import FeatureStatus
from devflow.core.tracker import IssueTracker


class _DummyTracker:
    """Minimal IssueTracker implementation for runtime_checkable tests."""

    @property
    def name(self) -> str:
        return "dummy"

    def check_available(self) -> tuple[bool, str]:
        return True, "ok"

    def create_issue(
        self, *, title: str, description: str, parent_id: str | None = None,
    ) -> str:
        return "DUMMY-1"

    def update_status(self, *, issue_id: str, status: FeatureStatus) -> None:
        pass

    def link_pr(self, *, issue_id: str, pr_url: str) -> None:
        pass


class TestIssueTrackerProtocol:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_DummyTracker(), IssueTracker)

    def test_non_tracker_fails_isinstance(self) -> None:
        assert not isinstance(object(), IssueTracker)

    def test_create_issue_returns_key(self) -> None:
        tracker = _DummyTracker()
        key = tracker.create_issue(title="test", description="desc")
        assert key == "DUMMY-1"

    def test_update_status_accepts_feature_status(self) -> None:
        tracker = _DummyTracker()
        tracker.update_status(issue_id="X", status=FeatureStatus.IMPLEMENTING)

    def test_link_pr_noop(self) -> None:
        tracker = _DummyTracker()
        tracker.link_pr(issue_id="X", pr_url="https://example.com/pr/1")
