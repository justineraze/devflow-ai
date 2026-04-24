"""Root conftest — shared fixtures for all tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _register_default_backend() -> None:
    """Ensure a backend is registered for tests that call get_backend().

    Without this, any test exercising code paths through the build loop
    would fail with RuntimeError since core/backend.py no longer
    auto-creates a ClaudeCodeBackend.
    """
    from devflow.core import backend as _mod
    from devflow.core.backend import set_backend
    from devflow.integrations.claude.backend import ClaudeCodeBackend

    set_backend(ClaudeCodeBackend())
    yield  # type: ignore[misc]
    _mod._current_backend = None
