"""Tests for double-review on critical paths."""

from __future__ import annotations

import json
from unittest.mock import patch

from devflow.core.config import DevflowConfig
from devflow.core.models import Feature, FeatureMetadata, PhaseName, PhaseRecord, PhaseStatus
from devflow.orchestration.phase_handlers import _needs_double_review


def _make_feature(
    feature_id: str = "feat-001",
    double_review_done: bool = False,
) -> Feature:
    return Feature(
        id=feature_id,
        description="test feature",
        status="implementing",
        workflow="standard",
        phases=[
            PhaseRecord(name=PhaseName.IMPLEMENTING, status=PhaseStatus.DONE),
            PhaseRecord(name=PhaseName.REVIEWING, status=PhaseStatus.IN_PROGRESS),
        ],
        metadata=FeatureMetadata(double_review_done=double_review_done),
    )


class TestNoConfigNoDoubleReview:
    def test_empty_config(self, tmp_path: object) -> None:
        feature = _make_feature()
        with patch("devflow.orchestration.phase_handlers.load_config") as mock_config, \
             patch("devflow.orchestration.phase_handlers.read_artifact") as mock_artifact:
            mock_config.return_value = DevflowConfig()
            mock_artifact.return_value = json.dumps({"paths": ["src/auth/login.py"]})
            assert _needs_double_review(feature, None) is False


class TestMatchingPathTriggersDouble:
    def test_auth_path_matches(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/auth/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact") as mock_artifact:
            mock_artifact.return_value = json.dumps({
                "paths": ["src/auth/login.py", "src/ui/display.py"],
            })
            assert _needs_double_review(feature, None) is True

    def test_payment_path_matches(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/payment/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact") as mock_artifact:
            mock_artifact.return_value = json.dumps({
                "paths": ["src/payment/checkout.py"],
            })
            assert _needs_double_review(feature, None) is True


class TestNonMatchingPathSingleReview:
    def test_ui_path_no_match(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/auth/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact") as mock_artifact:
            mock_artifact.return_value = json.dumps({
                "paths": ["src/ui/display.py", "src/cli.py"],
            })
            assert _needs_double_review(feature, None) is False


class TestDoubleReviewAlreadyDone:
    def test_skips_if_already_done(self) -> None:
        feature = _make_feature(double_review_done=True)
        assert _needs_double_review(feature, None) is False


class TestDoubleReviewNoFilesJson:
    def test_no_artifact(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/auth/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact", return_value=None):
            assert _needs_double_review(feature, None) is False

    def test_invalid_json(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/auth/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact", return_value="not json"):
            assert _needs_double_review(feature, None) is False


class TestMultiplePatterns:
    def test_any_pattern_matches(self) -> None:
        feature = _make_feature()
        config = DevflowConfig(double_review_on=["src/auth/**", "src/payment/**"])
        with patch("devflow.orchestration.phase_handlers.load_config", return_value=config), \
             patch("devflow.orchestration.phase_handlers.read_artifact") as mock_artifact:
            mock_artifact.return_value = json.dumps({
                "paths": ["src/payment/stripe.py"],
            })
            assert _needs_double_review(feature, None) is True
