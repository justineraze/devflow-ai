"""Project tracking: read/write feature state from .devflow/state.json."""

from __future__ import annotations

from pathlib import Path

from devflow.core.models import Feature, WorkflowState
from devflow.core.workflow import load_state


def get_state(base: Path | None = None) -> WorkflowState:
    """Load the current project state."""
    return load_state(base)


def get_feature(feature_id: str, base: Path | None = None) -> Feature | None:
    """Get a single feature by ID."""
    state = load_state(base)
    return state.get_feature(feature_id)


def list_all_features(base: Path | None = None) -> list[Feature]:
    """Return all features."""
    state = load_state(base)
    return list(state.features.values())
