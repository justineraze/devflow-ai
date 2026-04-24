"""Unified project configuration — .devflow/config.yaml.

All project-level settings live here: stack, base branch, gate commands,
Linear integration, and backend selection.  Runtime state (features,
timestamps) stays in state.json — this module handles only configuration.

The config file is OPTIONAL.  Without it, everything works with sensible
defaults (stack auto-detected, base_branch="main", backend="claude").
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class GateConfig(BaseModel):
    """Custom gate commands (optional overrides for auto-detection)."""

    lint: str | None = None
    test: str | None = None
    exclude: list[str] | None = None
    """Glob patterns for files/dirs to skip in all gate checks."""


class LinearConfig(BaseModel):
    """Linear integration settings."""

    team: str | None = None
    """Linear team key (e.g. 'ABC'). API key stays in env var."""


class DevflowConfig(BaseModel):
    """Unified project configuration persisted in .devflow/config.yaml."""

    stack: str | None = None
    """Primary language/stack (auto-detected, overridable)."""

    base_branch: str = "main"
    """Base branch for PRs."""

    gate: GateConfig = Field(default_factory=GateConfig)
    """Custom gate commands."""

    linear: LinearConfig = Field(default_factory=LinearConfig)
    """Linear integration settings."""

    backend: str = "claude"
    """AI backend to use (claude | gemini | openai | aider — only claude implemented)."""

    workflow: str | None = None
    """Workflow floor override (quick | light | standard | full).

    When set, the complexity scorer can upgrade but never downgrade below
    this level.  ``None`` means fully auto-selected by the scorer.
    """


# ── Paths ──────────────────────────────────────────────────────────

_CONFIG_FILE = "config.yaml"
_GATE_FILE = "gate.yaml"


def _config_path(base: Path | None = None) -> Path:
    return (base or Path.cwd()) / ".devflow" / _CONFIG_FILE


def _gate_path(base: Path | None = None) -> Path:
    return (base or Path.cwd()) / ".devflow" / _GATE_FILE


# ── Load ───────────────────────────────────────────────────────────


def _migrate_gate_yaml(base: Path | None = None) -> GateConfig | None:
    """If .devflow/gate.yaml exists, read it and delete the file.

    Returns a GateConfig to merge into the main config, or None.
    """
    path = _gate_path(base)
    if not path.is_file():
        return None

    data: Any = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not data:
        path.unlink(missing_ok=True)
        return None

    gate = GateConfig(
        lint=str(data["lint"]) if "lint" in data else None,
        test=str(data["test"]) if "test" in data else None,
    )
    path.unlink(missing_ok=True)
    log.info("Migrated gate.yaml into config.yaml")
    return gate


def _migrate_state_json(base: Path | None = None) -> dict[str, Any]:
    """If state.json contains config fields, extract them for migration.

    Returns a dict of fields to merge into config (may be empty).
    Does NOT modify state.json — the caller handles that.
    """
    import json

    state_path = (base or Path.cwd()) / ".devflow" / "state.json"
    if not state_path.is_file():
        return {}

    try:
        raw = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    migrated: dict[str, Any] = {}
    if raw.get("stack"):
        migrated["stack"] = raw["stack"]
    if raw.get("base_branch") and raw["base_branch"] != "main":
        migrated["base_branch"] = raw["base_branch"]
    if raw.get("linear_team_id"):
        migrated["linear_team"] = raw["linear_team_id"]

    return migrated


def load_config(base: Path | None = None) -> DevflowConfig:
    """Load project config from .devflow/config.yaml.

    Handles migrations from gate.yaml and state.json on first load.
    Returns defaults when the config file is absent.
    """
    path = _config_path(base)
    config = DevflowConfig()

    if path.is_file():
        raw: Any = yaml.safe_load(path.read_text())
        if isinstance(raw, dict):
            # Flatten nested sections for Pydantic.
            gate_raw = raw.pop("gate", None)
            linear_raw = raw.pop("linear", None)
            config = DevflowConfig(
                **{k: v for k, v in raw.items() if k in DevflowConfig.model_fields},
                gate=GateConfig(**(gate_raw or {})),
                linear=LinearConfig(**(linear_raw or {})),
            )

    # Migrate gate.yaml if it exists.
    migrated_gate = _migrate_gate_yaml(base)
    if migrated_gate:
        if migrated_gate.lint and not config.gate.lint:
            config.gate.lint = migrated_gate.lint
        if migrated_gate.test and not config.gate.test:
            config.gate.test = migrated_gate.test

    # Migrate state.json config fields.
    migrated_state = _migrate_state_json(base)
    if migrated_state:
        if migrated_state.get("stack") and not config.stack:
            config.stack = migrated_state["stack"]
        if migrated_state.get("base_branch") and config.base_branch == "main":
            config.base_branch = migrated_state["base_branch"]
        if migrated_state.get("linear_team") and not config.linear.team:
            config.linear.team = migrated_state["linear_team"]

    # Persist merged config if migrations occurred.
    if migrated_gate or migrated_state:
        save_config(config, base)

    return config


# ── Save ───────────────────────────────────────────────────────────


def save_config(config: DevflowConfig, base: Path | None = None) -> Path:
    """Persist config to .devflow/config.yaml (crash-safe via atomic write).

    Returns the path to the config file.
    """
    from devflow.core.paths import atomic_write_text
    from devflow.core.workflow import ensure_devflow_dir

    ensure_devflow_dir(base)
    path = _config_path(base)

    # Build a clean dict, omitting None values and empty sub-models.
    data: dict[str, Any] = {}
    if config.stack:
        data["stack"] = config.stack
    if config.base_branch != "main":
        data["base_branch"] = config.base_branch

    gate_dict: dict[str, Any] = {}
    if config.gate.lint:
        gate_dict["lint"] = config.gate.lint
    if config.gate.test:
        gate_dict["test"] = config.gate.test
    if config.gate.exclude:
        gate_dict["exclude"] = config.gate.exclude
    if gate_dict:
        data["gate"] = gate_dict

    linear_dict: dict[str, str] = {}
    if config.linear.team:
        linear_dict["team"] = config.linear.team
    if linear_dict:
        data["linear"] = linear_dict

    if config.backend != "claude":
        data["backend"] = config.backend

    if config.workflow is not None:
        data["workflow"] = config.workflow

    content = yaml.dump(data, default_flow_style=False, allow_unicode=True) if data else ""
    atomic_write_text(path, content)
    return path
