"""Unified project configuration — .devflow/config.yaml.

All project-level settings live here: stack, base branch, gate commands,
Linear integration, and backend selection.  Runtime state (features,
timestamps) stays in state.json — this module handles only configuration.

The config file is OPTIONAL.  Without it, everything works with sensible
defaults (stack auto-detected, base_branch="main", backend="claude").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

from devflow.core.paths import atomic_write_text
from devflow.core.workflow import ensure_devflow_dir

log = structlog.get_logger(__name__)

BACKEND_DEFAULT = "claude"
"""Default AI backend identifier."""


class GateConfig(BaseModel):
    """Custom gate commands (optional overrides for auto-detection)."""

    lint: str | None = None
    test: str | None = None
    exclude: list[str] | None = None
    """Glob patterns for files/dirs to skip in all gate checks."""
    diff_min_threshold: float = 0.95
    """Abort retry when consecutive diffs are more similar than this."""


class LinearConfig(BaseModel):
    """Linear integration settings."""

    team: str | None = None
    """Linear team key (e.g. 'ABC'). API key stays in env var."""


class PiModelsConfig(BaseModel):
    """Model mapping for Pi backend tiers."""

    fast: str = "anthropic/haiku"
    standard: str = "anthropic/sonnet"
    thinking: str = "anthropic/opus"


class PiConfig(BaseModel):
    """Pi backend settings."""

    models: PiModelsConfig = Field(default_factory=PiModelsConfig)


class BudgetConfig(BaseModel):
    """Cost budget settings."""

    per_feature_usd: float | None = None
    """Warning threshold per feature (soft limit, no hard fail)."""


class DevflowConfig(BaseModel):
    """Unified project configuration persisted in .devflow/config.yaml."""

    version: int = 1

    stack: str | None = None
    """Primary language/stack (auto-detected, overridable)."""

    base_branch: str = "main"
    """Base branch for PRs."""

    gate: GateConfig = Field(default_factory=GateConfig)
    """Custom gate commands."""

    linear: LinearConfig = Field(default_factory=LinearConfig)
    """Linear integration settings."""

    backend: str = BACKEND_DEFAULT
    """AI backend to use (claude | pi — extensible via Backend Protocol)."""

    workflow: str | None = None
    """Workflow floor override (quick | light | standard | full).

    When set, the complexity scorer can upgrade but never downgrade below
    this level.  ``None`` means fully auto-selected by the scorer.
    """

    pi: PiConfig = Field(default_factory=PiConfig)
    """Pi backend settings (model mapping per tier)."""

    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    """Cost budget settings."""

    double_review_on: list[str] = Field(default_factory=list)
    """Glob patterns for paths requiring two independent reviewers."""


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

    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
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
    state_path = (base or Path.cwd()) / ".devflow" / "state.json"
    if not state_path.is_file():
        return {}

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
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


# Process-scoped cache, keyed by config path. Invalidated by mtime so
# external edits are picked up automatically. Same pattern as load_state
# in workflow.py — keep them aligned if either changes.
_config_cache: dict[Path, tuple[float, DevflowConfig]] = {}


def clear_config_cache() -> None:
    """Drop the in-memory config cache (used in tests)."""
    _config_cache.clear()


def _load_config_uncached(path: Path, base: Path | None) -> DevflowConfig:
    """Read config from disk, run any pending migrations, and return it."""
    config = DevflowConfig()

    if path.is_file():
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            from devflow.core.migrations import CONFIG_VERSION, migrate_config

            raw_version = raw.get("version", 1)
            if raw_version < CONFIG_VERSION:
                raw = migrate_config(raw, raw_version, CONFIG_VERSION)
            elif "version" not in raw:
                raw["version"] = CONFIG_VERSION

            gate_raw = raw.get("gate")
            linear_raw = raw.get("linear")
            pi_raw = raw.get("pi")
            pi_models_raw = (pi_raw or {}).get("models")
            budget_raw = raw.get("budget")
            config = DevflowConfig(
                **{
                    k: v
                    for k, v in raw.items()
                    if k not in {"gate", "linear", "pi", "budget"}
                    and k in DevflowConfig.model_fields
                },
                gate=GateConfig(**(gate_raw or {})),
                linear=LinearConfig(**(linear_raw or {})),
                pi=PiConfig(
                    models=PiModelsConfig(**(pi_models_raw or {})),
                ),
                budget=BudgetConfig(**(budget_raw or {})),
            )

    migrated_gate = _migrate_gate_yaml(base)
    if migrated_gate:
        if migrated_gate.lint and not config.gate.lint:
            config.gate.lint = migrated_gate.lint
        if migrated_gate.test and not config.gate.test:
            config.gate.test = migrated_gate.test

    migrated_state = _migrate_state_json(base)
    if migrated_state:
        if migrated_state.get("stack") and not config.stack:
            config.stack = migrated_state["stack"]
        if migrated_state.get("base_branch") and config.base_branch == "main":
            config.base_branch = migrated_state["base_branch"]
        if migrated_state.get("linear_team") and not config.linear.team:
            config.linear.team = migrated_state["linear_team"]

    if migrated_gate or migrated_state:
        save_config(config, base)

    return config


def load_config(base: Path | None = None) -> DevflowConfig:
    """Load project config from .devflow/config.yaml.

    Handles migrations from gate.yaml and state.json on first load.
    Returns defaults when the config file is absent.

    Cached by mtime so subsequent calls within a build don't re-parse
    the YAML — the build loop calls this 8–10 times across modules.
    """
    path = _config_path(base)
    if path.is_file():
        mtime = path.stat().st_mtime
        cached = _config_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1].model_copy(deep=True)
        config = _load_config_uncached(path, base)
        # Re-stat: migrations may have written the file.
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        _config_cache[path] = (mtime, config)
        return config.model_copy(deep=True)

    # No file on disk — return defaults without caching (the file may
    # appear between calls and we don't want to mask that).
    return _load_config_uncached(path, base)


# ── Save ───────────────────────────────────────────────────────────


def save_config(config: DevflowConfig, base: Path | None = None) -> Path:
    """Persist config to .devflow/config.yaml (crash-safe via atomic write).

    Returns the path to the config file.
    """
    ensure_devflow_dir(base)
    path = _config_path(base)

    # Build a clean dict, omitting None values and empty sub-models.
    data: dict[str, Any] = {"version": config.version}
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
    if config.gate.diff_min_threshold != 0.95:
        gate_dict["diff_min_threshold"] = config.gate.diff_min_threshold
    if gate_dict:
        data["gate"] = gate_dict

    linear_dict: dict[str, str] = {}
    if config.linear.team:
        linear_dict["team"] = config.linear.team
    if linear_dict:
        data["linear"] = linear_dict

    if config.backend != BACKEND_DEFAULT:
        data["backend"] = config.backend

    if config.workflow is not None:
        data["workflow"] = config.workflow

    pi_defaults = PiModelsConfig()
    pi_models = config.pi.models
    if (
        pi_models.fast != pi_defaults.fast
        or pi_models.standard != pi_defaults.standard
        or pi_models.thinking != pi_defaults.thinking
    ):
        data["pi"] = {
            "models": {
                "fast": pi_models.fast,
                "standard": pi_models.standard,
                "thinking": pi_models.thinking,
            },
        }

    if config.budget.per_feature_usd is not None:
        data["budget"] = {"per_feature_usd": config.budget.per_feature_usd}

    if config.double_review_on:
        data["double_review_on"] = config.double_review_on

    content = yaml.dump(data, default_flow_style=False, allow_unicode=True) if data else ""
    atomic_write_text(path, content)
    _config_cache.pop(path, None)
    return path
