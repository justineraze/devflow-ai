"""Model routing — pick the cheapest model tier that fits the task.

Resolution order for a phase, first hit wins:

1. PhaseRecord.model — explicit override from the workflow YAML
   (still a string, mapped to ModelTier via ``_tier_from_legacy``).
2. A phase-specific selector that inspects artifacts (gate.json,
   files.json). Lets us downgrade to FAST for trivial fixes or
   STANDARD for small reviews.
3. PhaseSpec.model_default per phase (a ModelTier).
4. DEFAULT_TIER fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from devflow.core.artifacts import read_json_artifact
from devflow.core.backend import ModelTier
from devflow.core.models import Feature, PhaseName, PhaseRecord
from devflow.core.phases import UnknownPhase, get_spec
from devflow.core.workflow import load_workflow

DEFAULT_TIER = ModelTier.STANDARD

# String → ModelTier mapping for workflow YAML overrides.  Accepts both
# canonical tier names (fast/standard/thinking) and Claude-specific
# legacy aliases (haiku/sonnet/opus) for backwards compatibility.
# Other backends should add their own aliases here when needed.
_TIER_ALIASES: dict[str, ModelTier] = {
    # Canonical names.
    "fast": ModelTier.FAST,
    "standard": ModelTier.STANDARD,
    "thinking": ModelTier.THINKING,
    # Claude legacy aliases.
    "haiku": ModelTier.FAST,
    "sonnet": ModelTier.STANDARD,
    "opus": ModelTier.THINKING,
}


def _tier_from_string(name: str) -> ModelTier:
    """Convert a YAML model string (canonical tier or legacy alias) to ModelTier."""
    return _TIER_ALIASES.get(name.lower(), DEFAULT_TIER)


# Backwards-compat alias retained for any external imports.
_tier_from_legacy = _tier_from_string


# Stack → specialized developer agent.
STACK_AGENT_MAP: dict[str, str] = {
    "python": "developer-python",
    "typescript": "developer-typescript",
    "php": "developer-php",
}


def agent_for_stack(stack: str | None) -> str | None:
    """Return the specialized developer agent for *stack*, or None."""
    return STACK_AGENT_MAP.get(stack or "") or None

# Gate checks that are cheap, mechanical fixes (lint/format/secret
# patterns). When *all* failing checks are in this set, FAST tier
# handles the fix perfectly and costs ~10× less than STANDARD.
TRIVIAL_GATE_CHECKS: frozenset[str] = frozenset({
    "ruff", "biome", "pint", "secrets",
})

# Below this many lines, a small review fits comfortably in STANDARD's
# window of attention — THINKING's extra reasoning buys very little.
SMALL_DIFF_THRESHOLD = 50


Selector = Callable[..., ModelTier | None]


def _select_for_fixing(
    feature_id: str, base: Path | None, *, feature: Feature | None = None,
) -> ModelTier | None:
    """Pick the model tier for a fixing phase.

    On gate retry >= 2, the tier is forced from the escalation schedule
    stored in ``gate_retry_models`` (sonnet → opus). On retry 1 or
    first run, fall back to the trivial-gate heuristic (FAST for
    lint-only failures).
    """
    # Escalation override: retry 2+ forces a specific tier.
    if feature and feature.metadata.gate_retry >= 2:
        models = feature.metadata.gate_retry_models
        if models:
            last = models[-1]
            if last is not None:
                return _tier_from_legacy(last)

    data = read_json_artifact(feature_id, "gate.json", base)
    if not data:
        return None

    failing = [c for c in data.get("checks", []) if not c.get("passed", True)]
    if not failing:
        return None
    if all(c.get("name") in TRIVIAL_GATE_CHECKS for c in failing):
        return ModelTier.FAST
    return None


def _select_for_reviewing(feature_id: str, base: Path | None) -> ModelTier | None:
    """Downgrade THINKING → STANDARD for small, non-sensitive diffs."""
    data = read_json_artifact(feature_id, "files.json", base)
    if not data:
        return None

    if data.get("critical_paths"):
        return None

    total_lines = int(data.get("lines_added", 0)) + int(data.get("lines_removed", 0))
    if total_lines > 0 and total_lines < SMALL_DIFF_THRESHOLD:
        return ModelTier.STANDARD
    return None


PHASE_SELECTORS: dict[PhaseName, Selector] = {
    PhaseName.FIXING: _select_for_fixing,
    PhaseName.REVIEWING: _select_for_reviewing,
}


def resolve_model(
    feature: Feature,
    phase: PhaseRecord,
    base: Path | None = None,
) -> ModelTier:
    """Return the model tier to use for *phase*."""
    if phase.model:
        return _tier_from_legacy(phase.model)

    selector = PHASE_SELECTORS.get(phase.name)
    if selector is not None:
        if phase.name == PhaseName.FIXING:
            override = selector(feature.id, base, feature=feature)
        else:
            override = selector(feature.id, base)
        if override:
            return override

    try:
        return get_spec(phase.name).model_default
    except UnknownPhase:
        return DEFAULT_TIER


def get_phase_agent(
    feature: Feature,
    phase_name: str,
    base: Path | None = None,
    *,
    stack: str | None = None,
) -> str:
    """Return the agent name for a phase, with stack-aware override.

    Resolution: workflow YAML agent → stack-specialized developer → "developer".

    Pass *stack* explicitly to avoid a redundant ``load_state()`` call
    when the caller already knows the project stack (e.g. in the build loop).
    """
    agent = "developer"
    try:
        wf = load_workflow(feature.workflow)
        for phase_def in wf.phases:
            if phase_def.name == phase_name:
                agent = phase_def.agent
                break
    except FileNotFoundError:
        pass

    if agent == "developer":
        if stack is not None:
            resolved_stack = stack
        else:
            from devflow.core.config import load_config
            resolved_stack = load_config(base).stack
        specialized = agent_for_stack(resolved_stack)
        if specialized:
            agent = specialized

    return agent
