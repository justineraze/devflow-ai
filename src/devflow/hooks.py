"""User hooks -- execute .devflow/hooks/*.sh at key build moments."""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def run_hook(name: str, *args: str, cwd: Path | None = None) -> bool:
    """Run .devflow/hooks/{name}.sh if it exists. Returns True if OK or absent."""
    root = cwd or Path.cwd()
    hook = root / ".devflow" / "hooks" / f"{name}.sh"
    if not hook.is_file():
        return True
    log.info("Running hook", hook=name, path=str(hook))
    try:
        result = subprocess.run(
            ["sh", str(hook), *args],
            cwd=str(root),
            timeout=30,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.warning(
                "Hook failed",
                hook=name,
                exit_code=result.returncode,
                stderr=result.stderr[:500] if result.stderr else "",
            )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.warning("Hook timed out", hook=name)
        return False
    except OSError as exc:
        log.warning("Hook error", hook=name, error=str(exc))
        return False
