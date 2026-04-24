"""Tests for devflow.core.track — project state reading."""

from pathlib import Path

import pytest

from devflow.core.models import Feature, FeatureStatus, WorkflowState
from devflow.core.track import (
    get_feature,
    get_state,
    list_all_features,
)
from devflow.core.workflow import save_state


@pytest.fixture
def project_with_features(tmp_path: Path) -> Path:
    """Create a project directory with two features in state."""
    state = WorkflowState()
    state.add_feature(Feature(id="f-001", description="Active feature"))
    feat_done = Feature(id="f-002", description="Done feature", status=FeatureStatus.DONE)
    state.add_feature(feat_done)
    save_state(state, tmp_path)
    return tmp_path


class TestGetState:
    def test_empty_project(self, tmp_path: Path) -> None:
        state = get_state(tmp_path)
        assert len(state.features) == 0

    def test_project_with_features(self, project_with_features: Path) -> None:
        state = get_state(project_with_features)
        assert len(state.features) == 2


class TestGetFeature:
    def test_existing_feature(self, project_with_features: Path) -> None:
        feat = get_feature("f-001", project_with_features)
        assert feat is not None
        assert feat.description == "Active feature"

    def test_missing_feature(self, project_with_features: Path) -> None:
        assert get_feature("nope", project_with_features) is None


class TestListFeatures:
    def test_all_features(self, project_with_features: Path) -> None:
        all_feats = list_all_features(project_with_features)
        assert len(all_feats) == 2
