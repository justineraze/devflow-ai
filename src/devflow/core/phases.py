"""Single source of truth for everything about a phase.

A *phase* is a step in the build state machine (planning, implementing,
reviewing, …). Each phase has stable metadata that several modules
need: which feature status it maps to, which skills get injected,
which model to use by default, which previous artifacts it depends on,
and the natural-language instructions sent to the agent.

Before this module that metadata was scattered across five dicts in
five files; adding a new phase meant editing all of them and hoping no
typo slipped through. Now each phase is one ``PhaseSpec`` entry in
``PHASES``, every consumer reads from the same registry, and the
``PhaseName`` enum makes typos a compile-time error.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, model_validator

from devflow.core.backend import ModelTier
from devflow.core.models import FeatureStatus, PhaseName, PhaseType


class PhaseSpec(BaseModel):
    """Static metadata for one phase of the build state machine."""

    model_config = {"frozen": True}

    name: PhaseName
    phase_type: PhaseType
    feature_status: FeatureStatus
    model_default: ModelTier
    skills: tuple[str, ...] = ()
    context_deps: tuple[PhaseName, ...] = ()
    instructions: str = ""
    runs_claude: bool = True

    @model_validator(mode="after")
    def _no_self_dep(self) -> Self:
        if self.name in self.context_deps:
            raise ValueError(f"Phase {self.name} cannot depend on itself")
        return self


_INSTRUCTIONS_ARCHITECTURE = (
    "## Instructions\n\n"
    "Analyze the feature scope and produce architectural decisions.\n"
    "Output your analysis in the format specified in your agent instructions.\n"
    "Focus on module boundaries, dependency impact, and data flow."
)

_INSTRUCTIONS_PLANNING = (
    "## Instructions\n\n"
    "Create a step-by-step implementation plan for this feature.\n"
    "Output your plan in the structured format from your agent instructions.\n"
    "Each step must name the exact file and what to change."
)

_INSTRUCTIONS_PLAN_REVIEW = (
    "## Instructions\n\n"
    "Review the plan from the planning phase.\n"
    "Check for completeness, risks, and missing test coverage.\n"
    "Output APPROVE or REQUEST_CHANGES with specific feedback."
)

_INSTRUCTIONS_IMPLEMENTING = (
    "## Instructions\n\n"
    "Implement the plan step by step.\n"
    "Follow the plan exactly — one step at a time.\n"
    "Write tests alongside the code.\n"
    "Run ruff and pytest after each change.\n\n"
    "**IMPORTANT — Commits atomiques obligatoires:**\n"
    "After completing each plan step, you MUST run:\n"
    "  git add -A && git commit -m 'feat: <short description of step>'\n"
    "Do NOT batch multiple steps into a single commit.\n"
    "Each commit = one plan step, verified green (ruff + pytest pass)."
)

_INSTRUCTIONS_IMPLEMENTING_QUICK = (
    "## Instructions\n\n"
    "Implement the requested change.\n"
    "Write tests alongside the code.\n"
    "Run ruff and pytest after each change.\n\n"
    "**IMPORTANT — Do NOT commit.**\n"
    "Do NOT run git add, git commit, or any git command.\n"
    "The caller will handle the single commit after you're done."
)

_INSTRUCTIONS_REVIEWING = (
    "## Instructions\n\n"
    "Review the implementation changes.\n"
    "Run: git diff to see all changes made during implementation.\n"
    "Check against the plan, look for bugs, security issues, and "
    "convention violations.\n"
    "Output your review in the structured format from your agent "
    "instructions."
)

_INSTRUCTIONS_FIXING = (
    "## Instructions\n\n"
    "Address the review feedback from the reviewing phase.\n"
    "Fix each issue flagged as critical or warning.\n"
    "Run tests after each fix.\n\n"
    "**Commit each fix separately:**\n"
    "  git add -A && git commit -m 'fix: <short description>'\n"
    "Do NOT batch multiple fixes into one commit."
)


PHASES: dict[PhaseName, PhaseSpec] = {
    PhaseName.ARCHITECTURE: PhaseSpec(
        name=PhaseName.ARCHITECTURE,
        phase_type=PhaseType.PLANNING,
        feature_status=FeatureStatus.PLANNING,
        model_default=ModelTier.THINKING,
        skills=("devflow-planning",),
        context_deps=(),
        instructions=_INSTRUCTIONS_ARCHITECTURE,
    ),
    PhaseName.PLANNING: PhaseSpec(
        name=PhaseName.PLANNING,
        phase_type=PhaseType.PLANNING,
        feature_status=FeatureStatus.PLANNING,
        model_default=ModelTier.THINKING,
        skills=("devflow-planning",),
        context_deps=(PhaseName.ARCHITECTURE,),
        instructions=_INSTRUCTIONS_PLANNING,
    ),
    PhaseName.PLAN_REVIEW: PhaseSpec(
        name=PhaseName.PLAN_REVIEW,
        phase_type=PhaseType.PLANNING,
        feature_status=FeatureStatus.PLAN_REVIEW,
        model_default=ModelTier.STANDARD,
        skills=("devflow-review", "devflow-planning"),
        context_deps=(PhaseName.PLANNING,),
        instructions=_INSTRUCTIONS_PLAN_REVIEW,
    ),
    PhaseName.IMPLEMENTING: PhaseSpec(
        name=PhaseName.IMPLEMENTING,
        phase_type=PhaseType.CODE,
        feature_status=FeatureStatus.IMPLEMENTING,
        model_default=ModelTier.STANDARD,
        skills=("devflow-incremental", "devflow-tdd"),
        context_deps=(PhaseName.PLANNING,),
        instructions=_INSTRUCTIONS_IMPLEMENTING,
    ),
    PhaseName.REVIEWING: PhaseSpec(
        name=PhaseName.REVIEWING,
        phase_type=PhaseType.REVIEW,
        feature_status=FeatureStatus.REVIEWING,
        model_default=ModelTier.THINKING,
        skills=("devflow-review", "devflow-refactor"),
        context_deps=(PhaseName.PLANNING,),
        instructions=_INSTRUCTIONS_REVIEWING,
    ),
    PhaseName.FIXING: PhaseSpec(
        name=PhaseName.FIXING,
        phase_type=PhaseType.CODE,
        feature_status=FeatureStatus.FIXING,
        model_default=ModelTier.STANDARD,
        skills=("devflow-debug", "devflow-incremental", "devflow-tdd"),
        context_deps=(PhaseName.REVIEWING,),
        instructions=_INSTRUCTIONS_FIXING,
    ),
    PhaseName.GATE: PhaseSpec(
        name=PhaseName.GATE,
        phase_type=PhaseType.GATE,
        feature_status=FeatureStatus.GATE,
        model_default=ModelTier.STANDARD,
        skills=(),
        context_deps=(),
        instructions="",
        runs_claude=False,
    ),
}


class UnknownPhase(KeyError):
    """Raised when a phase name has no entry in the registry."""

    def __init__(self, name: object) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        valid = ", ".join(p.value for p in PhaseName)
        return f"unknown phase {self.name!r}; expected one of: {valid}"


def get_spec(name: str | PhaseName) -> PhaseSpec:
    """Return the registry entry for *name*.

    Accepts both raw strings (workflow YAML, persisted state) and
    PhaseName members. Raises UnknownPhase when no entry exists so the
    caller can surface a friendly error instead of a bare KeyError.
    """
    try:
        key = PhaseName(name)
    except ValueError as exc:
        raise UnknownPhase(name) from exc
    spec = PHASES.get(key)
    if spec is None:
        raise UnknownPhase(name)
    return spec


def is_known_phase(name: str | PhaseName) -> bool:
    """Return True when *name* maps to a registered PhaseSpec."""
    try:
        get_spec(name)
    except UnknownPhase:
        return False
    return True


__all__ = [
    "PHASES",
    "PhaseName",
    "PhaseSpec",
    "UnknownPhase",
    "get_spec",
    "is_known_phase",
]
