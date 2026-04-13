"""Per-feature artifacts stored under .devflow/<feat-id>/.

Each phase's textual output is persisted as <phase_name>.md so downstream
phases can load only the artifacts they actually need, instead of receiving
the concatenated outputs of every previous phase. This keeps the user
prompt compact and stable enough to benefit from prompt caching.
"""

from __future__ import annotations

from pathlib import Path

from devflow.core.workflow import ensure_devflow_dir


def feature_dir(feature_id: str, base: Path | None = None) -> Path:
    """Return .devflow/<feature_id>/, creating it if missing."""
    devflow = ensure_devflow_dir(base)
    path = devflow / feature_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(feature_id: str, name: str, base: Path | None = None) -> Path:
    """Return the path for a named artifact (e.g. 'planning.md')."""
    return feature_dir(feature_id, base) / name


def write_artifact(
    feature_id: str, name: str, content: str, base: Path | None = None,
) -> Path:
    """Write an artifact atomically (tmp + rename) to avoid partial writes."""
    target = artifact_path(feature_id, name, base)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.rename(target)
    return target


def read_artifact(
    feature_id: str, name: str, base: Path | None = None,
) -> str | None:
    """Read an artifact's content, or None if missing."""
    target = artifact_path(feature_id, name, base)
    if not target.exists():
        return None
    return target.read_text()


def save_phase_output(
    feature_id: str, phase_name: str, output: str, base: Path | None = None,
) -> Path:
    """Persist a phase's textual output as <phase_name>.md."""
    return write_artifact(feature_id, f"{phase_name}.md", output, base)


def load_phase_output(
    feature_id: str, phase_name: str, base: Path | None = None,
) -> str | None:
    """Load a persisted phase output, or None if missing."""
    return read_artifact(feature_id, f"{phase_name}.md", base)


# Which previous phases each phase needs as context. Keeping this narrow
# is the whole point: reviewing doesn't need architecture's exploration
# output, fixing only needs the review findings, gate needs nothing.
PHASE_CONTEXT_DEPS: dict[str, tuple[str, ...]] = {
    "architecture": (),
    "planning": ("architecture",),
    "plan_review": ("planning",),
    "implementing": ("planning",),
    "reviewing": ("planning",),
    "fixing": ("reviewing",),
    "gate": (),
}


def context_deps_for(phase_name: str) -> tuple[str, ...]:
    """Return the phase names whose outputs should be injected as context."""
    return PHASE_CONTEXT_DEPS.get(phase_name, ())
