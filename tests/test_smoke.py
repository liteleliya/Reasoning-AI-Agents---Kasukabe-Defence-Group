"""Smoke test: every package imports and carries a docstring."""

import importlib

import pytest

PACKAGES = [
    "blackboard",
    "protocol",
    "scheduler",
    "agents",
    "counterfactual",
    "server",
    "bench",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__
