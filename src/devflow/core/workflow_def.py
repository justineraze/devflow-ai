"""Workflow YAML schema — DTOs loaded by :mod:`devflow.core.workflow`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devflow.core.models import PhaseName


class PhaseDefinition(BaseModel):
    """Definition of a phase in a workflow YAML file."""

    name: PhaseName
    agent: str = ""
    description: str = ""
    required: bool = True
    timeout: int = 300
    model: str | None = None


class WorkflowDefinition(BaseModel):
    """Definition of a complete workflow loaded from YAML."""

    name: str
    description: str = ""
    phases: list[PhaseDefinition] = Field(default_factory=list)


__all__ = ["PhaseDefinition", "WorkflowDefinition"]
