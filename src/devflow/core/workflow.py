"""Workflow engine: YAML loading, state persistence, and phase transitions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml

from devflow.core.models import (
    Feature,
    PhaseDefinition,
    PhaseRecord,
    PhaseStatus,
    WorkflowDefinition,
    WorkflowState,
)
from devflow.core.paths import atomic_write_text
from devflow.core.paths import workflows_dir as _workflows_dir

# Default location for project state.
DEVFLOW_DIR = Path(".devflow")
STATE_FILE = DEVFLOW_DIR / "state.json"

# Where workflow definitions live (relative to package root).
WORKFLOWS_DIR = _workflows_dir()


_workflow_cache: dict[str, WorkflowDefinition] = {}


def load_workflow(name: str, workflows_dir: Path | None = None) -> WorkflowDefinition:
    """Load a workflow definition from a YAML file.

    Results are cached by *name* when using the default workflows
    directory. Pass *workflows_dir* explicitly to bypass the cache
    (used in tests with temporary directories).

    Args:
        name: Workflow name (without .yaml extension).
        workflows_dir: Directory containing workflow YAML files.
                       Defaults to the repo's workflows/ directory.

    Raises:
        FileNotFoundError: If the workflow file doesn't exist.
    """
    if workflows_dir is None and name in _workflow_cache:
        return _workflow_cache[name]

    base = workflows_dir or WORKFLOWS_DIR
    path = base / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {path}")

    raw = yaml.safe_load(path.read_text())
    phases = [PhaseDefinition(**p) for p in raw.get("phases", [])]
    wf = WorkflowDefinition(
        name=raw.get("name", name),
        description=raw.get("description", ""),
        phases=phases,
    )

    if workflows_dir is None:
        _workflow_cache[name] = wf
    return wf


def ensure_devflow_dir(base: Path | None = None) -> Path:
    """Create .devflow/ directory if it doesn't exist. Returns the path."""
    devflow = (base or Path.cwd()) / ".devflow"
    devflow.mkdir(parents=True, exist_ok=True)
    return devflow


def load_state(base: Path | None = None) -> WorkflowState:
    """Load project state from .devflow/state.json.

    Returns an empty WorkflowState if the file doesn't exist yet.
    """
    state_file = (base or Path.cwd()) / ".devflow" / "state.json"
    if not state_file.exists():
        return WorkflowState()
    raw = json.loads(state_file.read_text())
    return WorkflowState.model_validate(raw)


def save_state(state: WorkflowState, base: Path | None = None) -> Path:
    """Persist project state to .devflow/state.json (crash-safe via tmp + rename).

    Returns the path to the state file.
    """
    devflow = ensure_devflow_dir(base)
    state_file = devflow / "state.json"
    atomic_write_text(state_file, state.model_dump_json(indent=2))
    return state_file


@contextmanager
def mutate_feature(
    feature_id: str, base: Path | None = None,
) -> Iterator[Feature | None]:
    """Load a feature, yield it for mutation, persist state on exit.

    Replaces the ``load_state → get_feature → … → save_state`` triple that
    appears in ``phase_exec.py``, ``lifecycle.py``, and ``build.py``.

    When the feature is missing, yields ``None`` and skips the final
    ``save_state`` — callers already guarded against this case, so the
    semantics are unchanged. Callers must check for ``None`` inside
    the block.
    """
    state = load_state(base)
    feature = state.get_feature(feature_id)
    yield feature
    if feature is not None:
        save_state(state, base)


def create_feature(
    state: WorkflowState,
    feature_id: str,
    description: str,
    workflow_name: str = "standard",
    workflows_dir: Path | None = None,
) -> Feature:
    """Create a new feature with phases from the workflow definition.

    Args:
        state: Current project state (modified in place).
        feature_id: Unique identifier for the feature.
        description: Human-readable description.
        workflow_name: Which workflow YAML to use.
        workflows_dir: Override for workflow directory.

    Returns:
        The newly created Feature.

    Raises:
        ValueError: If a feature with this ID already exists.
    """
    if feature_id in state.features:
        raise ValueError(f"Feature {feature_id!r} already exists")

    workflow = load_workflow(workflow_name, workflows_dir)
    phases = [PhaseRecord(name=p.name, model=p.model) for p in workflow.phases]

    feature = Feature(
        id=feature_id,
        description=description,
        workflow=workflow_name,
        phases=phases,
    )
    state.add_feature(feature)
    return feature


def advance_phase(feature: Feature) -> PhaseRecord | None:
    """Start the next pending phase in a feature.

    Returns the started PhaseRecord, or None if all phases are done.
    """
    for phase in feature.phases:
        if phase.status == PhaseStatus.PENDING:
            phase.start()
            return phase
    return None
