"""Behavior tests for the public API of trace_sampling_policy."""

from __future__ import annotations

import pytest

import trace_sampling_policy


def test_normalize_trims_and_lowercases() -> None:
    assert trace_sampling_policy.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        trace_sampling_policy.normalize(value)


def test_version_is_semver() -> None:
    parts = trace_sampling_policy.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
