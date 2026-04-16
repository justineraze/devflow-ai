"""Tests for the calculator module."""

from src.calculator import add


def test_add_positive() -> None:
    assert add(2, 3) == 5


def test_add_negative() -> None:
    assert add(-1, 1) == 0


def test_add_zeros() -> None:
    assert add(0, 0) == 0
