"""Contract tests — verify that every Backend implementation satisfies the Protocol."""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from devflow.core.backend import Backend, ModelTier
from devflow.integrations.claude.backend import ClaudeCodeBackend
from devflow.integrations.pi.backend import PiBackend


def _all_backends() -> list[Backend]:
    """Collect all registered backends for contract testing."""
    return [ClaudeCodeBackend(), PiBackend()]


@pytest.fixture(params=_all_backends(), ids=lambda b: b.name)
def backend(request: pytest.FixtureRequest) -> Backend:
    return request.param


@pytest.mark.contract
class TestBackendContract:
    def test_is_backend_protocol(self, backend: Backend) -> None:
        assert isinstance(backend, Backend)

    def test_name_is_nonempty_str(self, backend: Backend) -> None:
        assert isinstance(backend.name, str)
        assert len(backend.name) > 0

    def test_model_name_returns_str(self, backend: Backend) -> None:
        for tier in ModelTier:
            result = backend.model_name(tier)
            assert isinstance(result, str), f"model_name({tier}) returned {type(result)}"
            assert len(result) > 0, f"model_name({tier}) returned empty string"

    def test_check_available_returns_tuple(self, backend: Backend) -> None:
        result = backend.check_available()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_execute_is_callable(self, backend: Backend) -> None:
        assert callable(backend.execute)
        sig = inspect.signature(backend.execute)
        expected = {
            "system_prompt", "user_prompt", "model",
            "timeout", "cwd", "env", "on_tool",
        }
        actual = {p for p in sig.parameters if p != "self"}
        assert expected <= actual, f"Missing: {expected - actual}"

    def test_one_shot_is_callable(self, backend: Backend) -> None:
        assert callable(backend.one_shot)
        sig = inspect.signature(backend.one_shot)
        expected = {"system", "user", "model", "timeout"}
        actual = {p for p in sig.parameters if p != "self"}
        assert expected <= actual, f"Missing: {expected - actual}"

    def test_execute_returns_correct_type_hints(self, backend: Backend) -> None:
        hints = get_type_hints(type(backend).execute)
        assert "return" in hints

    def test_one_shot_returns_correct_type_hints(self, backend: Backend) -> None:
        hints = get_type_hints(type(backend).one_shot)
        assert "return" in hints
