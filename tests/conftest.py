"""Root conftest — shared fixtures for all tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _register_default_backend() -> Generator[None, None, None]:
    from devflow.core.backend import clear_backend, set_backend
    from devflow.integrations.claude.backend import ClaudeCodeBackend

    set_backend(ClaudeCodeBackend())
    yield
    clear_backend()
