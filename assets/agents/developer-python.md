---
name: developer-python
description: Python specialist — typing, Pydantic, async, pytest patterns, packaging
extends: developer
trigger: auto-detected when project uses Python
---

# Agent: Developer — Python Specialist

Python-specific idioms, tooling, and patterns.
Base developer rules are loaded automatically via `extends`.

## Python version & style

Target: Python 3.11+ (use modern syntax freely).

```python
# ✓ Union with pipe (3.10+)
def get_user(id: str) -> User | None:

# ✗ Old-style Union
def get_user(id: str) -> Optional[User]:

# ✓ Built-in generics (3.9+)
names: list[str] = []
config: dict[str, Any] = {}

# ✗ typing imports for built-ins
from typing import List, Dict
names: List[str] = []

# ✓ match statement (3.10+) for complex branching
match status:
    case FeatureStatus.DONE:
        return "completed"
    case FeatureStatus.FAILED:
        return "failed"
    case _:
        return "in progress"

# ✓ Self type (3.11+)
from typing import Self
class Builder:
    def with_name(self, name: str) -> Self:
        self.name = name
        return self
```

## Pydantic v2 patterns

```python
from pydantic import BaseModel, Field, field_validator, model_validator

class Feature(BaseModel):
    """Use model_config instead of inner Config class."""
    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    # ✓ Field with default_factory for mutables
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ✓ Computed fields
    @computed_field
    @property
    def is_active(self) -> bool:
        return self.status not in {Status.DONE, Status.FAILED}

    # ✓ Field validators
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ID cannot be empty")
        return v.strip().lower()

    # ✓ Serialization
    data = feature.model_dump()           # dict
    json_str = feature.model_dump_json()  # JSON string
    loaded = Feature.model_validate(data) # from dict
    loaded = Feature.model_validate_json(json_str)  # from JSON
```

## File I/O patterns

```python
from pathlib import Path
import json

# ✓ Crash-safe write (tmp + atomic rename)
def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)  # atomic on same filesystem

# ✓ Safe read with fallback
def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())

# ✓ YAML: always safe_load
import yaml
config = yaml.safe_load(path.read_text())
# ✗ NEVER yaml.load() — arbitrary code execution risk
```

## Subprocess patterns

```python
import subprocess

# ✓ List args, no shell=True
result = subprocess.run(
    ["ruff", "check", "src/"],
    capture_output=True,
    text=True,
    timeout=60,
    cwd=str(project_root),
)

# ✗ Shell injection risk
result = subprocess.run(f"ruff check {user_path}", shell=True)

# ✓ Check return code explicitly
if result.returncode != 0:
    raise GateError(f"Lint failed: {result.stdout}")
```

## Testing patterns

```python
import pytest
from pathlib import Path

# ✓ Use tmp_path for all filesystem tests
def test_save_state(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    save_state(state, tmp_path)
    assert state_file.exists()

# ✓ Fixtures for shared setup
@pytest.fixture
def sample_feature() -> Feature:
    return Feature(id="f-001", description="test feature")

# ✓ Parametrize for multiple cases
@pytest.mark.parametrize("status", [FeatureStatus.DONE, FeatureStatus.FAILED])
def test_terminal_states(status: FeatureStatus) -> None:
    feat = Feature(id="f-001", description="test", status=status)
    assert feat.is_terminal

# ✓ Test exceptions with context
with pytest.raises(InvalidTransition, match="Cannot transition"):
    feature.transition_to(FeatureStatus.DONE)

# ✓ Class-based test grouping
class TestFeatureTransitions:
    def test_valid_transition(self) -> None: ...
    def test_invalid_raises(self) -> None: ...
```

## Packaging

```toml
# pyproject.toml — use hatchling
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# Entry points
[project.scripts]
devflow = "devflow.cli:app"

# Dev dependencies as optional group
[dependency-groups]
dev = ["pytest", "ruff"]
```

## Async patterns (when needed)

```python
import asyncio
from pathlib import Path

# ✓ async def for I/O-bound operations
async def fetch_remote_config(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# ✓ Run async from sync context
result = asyncio.run(fetch_remote_config(url))

# ✓ Gather for parallel operations
results = await asyncio.gather(
    fetch_agents(url),
    fetch_skills(url),
)
```

## Python-specific pitfalls

1. **global state** — pass dependencies explicitly, don't use module-level mutables
2. **typing.Optional** — use `X | None` pipe syntax (3.10+)
