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


def archive_feature(feature_id: str, project_root: Path | None = None) -> Path:
    """Move ``.devflow/<feature_id>/`` to ``.devflow/.archive/<feature_id>/``.

    Creates ``.devflow/.archive/`` if needed.
    Returns the destination path.
    Raises ``FileNotFoundError`` if the feature directory does not exist.
    """
    from devflow.core.workflow import ensure_devflow_dir

    devflow = ensure_devflow_dir(project_root)
    src = devflow / feature_id
    if not src.exists():
        raise FileNotFoundError(f"Feature dir not found: {src}")

    archive_dir = devflow / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    dest = archive_dir / feature_id
    src.rename(dest)
    return dest


def context_deps_for(phase_name: str) -> tuple[str, ...]:
    """Return the phase names whose outputs should be injected as context."""
    from devflow.core.phases import UnknownPhase, get_spec

    try:
        return tuple(dep.value for dep in get_spec(phase_name).context_deps)
    except UnknownPhase:
        return ()
