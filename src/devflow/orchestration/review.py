"""Review cycle logic — re-review and re-fix after implementing/fixing.

Extracted from build.py to keep the execution loop focused on dispatch.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.models import Feature, FeatureStatus, PhaseName
from devflow.core.workflow import mutate_feature
from devflow.orchestration.lifecycle import transition_safe

MAX_REVIEW_CYCLES = 2


def should_re_review(feature: Feature, base: Path | None = None) -> bool:
    """Return True if the workflow has a reviewing phase and review budget remains."""
    if feature.metadata.review_cycles >= MAX_REVIEW_CYCLES:
        return False
    return feature.find_phase(PhaseName.REVIEWING) is not None


def setup_re_review(feature_id: str, base: Path | None = None) -> None:
    """Reset reviewing to PENDING after fixing, incrementing review_cycles."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        reviewing = feature.find_phase(PhaseName.REVIEWING)
        if reviewing:
            reviewing.reset()
        feature.metadata.review_cycles += 1


def setup_re_fix(feature_id: str, base: Path | None = None) -> None:
    """Reset fixing+gate to PENDING after a reviewer REQUEST_CHANGES."""
    with mutate_feature(feature_id, base) as feature:
        if not feature:
            return
        fixing = feature.find_phase(PhaseName.FIXING)
        if fixing:
            fixing.reset()
        gate = feature.find_phase(PhaseName.GATE)
        if gate:
            gate.reset()
        transition_safe(feature, FeatureStatus.FIXING)
