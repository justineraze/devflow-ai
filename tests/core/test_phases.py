"""Tests for the unified phase registry."""

from __future__ import annotations

import pytest

from devflow.core.models import FeatureStatus, PhaseName
from devflow.core.phases import (
    PHASES,
    PhaseSpec,
    UnknownPhase,
    get_spec,
    is_known_phase,
)


class TestPhaseSpec:
    def test_self_dependency_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot depend on itself"):
            PhaseSpec(
                name=PhaseName.PLANNING,
                feature_status=FeatureStatus.PLANNING,
                model_default="opus",
                context_deps=(PhaseName.PLANNING,),
            )

    def test_spec_is_frozen(self) -> None:
        spec = get_spec(PhaseName.PLANNING)
        with pytest.raises((TypeError, ValueError)):
            spec.model_default = "haiku"


class TestRegistryShape:
    """Every PhaseName must have exactly one PhaseSpec, and vice-versa."""

    def test_every_phase_name_has_a_spec(self) -> None:
        missing = [name for name in PhaseName if name not in PHASES]
        assert not missing, f"Missing specs: {missing}"

    def test_every_spec_key_matches_its_name(self) -> None:
        mismatched = [
            (key, spec.name) for key, spec in PHASES.items()
            if key != spec.name
        ]
        assert not mismatched, f"Spec key/name mismatch: {mismatched}"

    def test_only_gate_skips_claude(self) -> None:
        non_claude = {n for n, s in PHASES.items() if not s.runs_claude}
        assert non_claude == {PhaseName.GATE}


class TestRegistryConsistency:
    """Specs must reference only known phases and known statuses."""

    def test_context_deps_only_reference_known_phases(self) -> None:
        for spec in PHASES.values():
            for dep in spec.context_deps:
                assert dep in PHASES, f"{spec.name} → unknown dep {dep}"

    def test_no_phase_depends_on_a_later_one(self) -> None:
        order = list(PhaseName)
        for spec in PHASES.values():
            idx = order.index(spec.name)
            for dep in spec.context_deps:
                assert order.index(dep) < idx, (
                    f"{spec.name} depends on later phase {dep}"
                )

    def test_feature_status_is_a_real_status(self) -> None:
        for spec in PHASES.values():
            assert isinstance(spec.feature_status, FeatureStatus)


class TestAccessors:
    def test_get_spec_accepts_string(self) -> None:
        assert get_spec("planning").name is PhaseName.PLANNING

    def test_get_spec_accepts_enum(self) -> None:
        assert get_spec(PhaseName.PLANNING).name is PhaseName.PLANNING

    def test_get_spec_unknown_raises_friendly_error(self) -> None:
        with pytest.raises(UnknownPhase) as exc:
            get_spec("nonexistent")
        assert "nonexistent" in str(exc.value)
        assert "planning" in str(exc.value)

    def test_is_known_phase_true_for_registered(self) -> None:
        assert is_known_phase("fixing") is True
        assert is_known_phase(PhaseName.FIXING) is True

    def test_is_known_phase_false_for_unregistered(self) -> None:
        assert is_known_phase("nope") is False
