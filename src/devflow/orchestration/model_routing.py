"""Model routing — pick the cheapest Claude model that fits the task.

Resolution order for a phase, first hit wins:

1. PhaseRecord.model — explicit override from the workflow YAML.
2. A phase-specific selector that inspects artifacts (gate.json,
   files.json). Lets us downgrade to Haiku for trivial fixes or
   Sonnet for small reviews without changing PHASE_MODELS.
3. PHASE_MODELS default per phase.
4. DEFAULT_MODEL fallback.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devflow.core.artifacts import read_artifact
from devflow.core.models import Feature, PhaseName, PhaseRecord
from devflow.core.phases import UnknownPhase, get_spec

DEFAULT_MODEL = "sonnet"

# Gate checks that are cheap, mechanical fixes (lint/format/secret
# patterns). When *all* failing checks are in this set, Haiku handles
# the fix perfectly and costs ~10× less than Sonnet.
TRIVIAL_GATE_CHECKS: frozenset[str] = frozenset({
    "ruff", "biome", "pint", "secrets",
})

# Below this many lines, a small review fits comfortably in Sonnet's
# window of attention — Opus's extra reasoning buys very little.
SMALL_DIFF_THRESHOLD = 50


Selector = Callable[[str, Path | None], str | None]


def _select_for_fixing(feature_id: str, base: Path | None) -> str | None:
    """Haiku when the gate report only complains about trivial tools."""
    raw = read_artifact(feature_id, "gate.json", base)
    if not raw:
        return None
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None

    failing = [c for c in data.get("checks", []) if not c.get("passed", True)]
    if not failing:
        return None
    if all(c.get("name") in TRIVIAL_GATE_CHECKS for c in failing):
        return "haiku"
    return None


def _select_for_reviewing(feature_id: str, base: Path | None) -> str | None:
    """Downgrade Opus → Sonnet for small, non-sensitive diffs."""
    raw = read_artifact(feature_id, "files.json", base)
    if not raw:
        return None
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if data.get("critical_paths"):
        return None

    total_lines = int(data.get("lines_added", 0)) + int(data.get("lines_removed", 0))
    if total_lines > 0 and total_lines < SMALL_DIFF_THRESHOLD:
        return "sonnet"
    return None


PHASE_SELECTORS: dict[PhaseName, Selector] = {
    PhaseName.FIXING: _select_for_fixing,
    PhaseName.REVIEWING: _select_for_reviewing,
}


def resolve_model(
    feature: Feature,
    phase: PhaseRecord,
    base: Path | None = None,
) -> str:
    """Return the Claude model alias to use for *phase*."""
    if phase.model:
        return phase.model

    selector = PHASE_SELECTORS.get(phase.name)
    if selector is not None:
        override = selector(feature.id, base)
        if override:
            return override

    try:
        return get_spec(phase.name).model_default
    except UnknownPhase:
        return DEFAULT_MODEL
