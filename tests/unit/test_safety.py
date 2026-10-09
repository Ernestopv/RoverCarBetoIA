"""Tests for the safety layer."""

from __future__ import annotations

import math

import pytest

from app.core.exceptions import InvalidMotionCommandError
from app.rover.safety import SafetyLayer, SafetyLimits


@pytest.fixture
def layer() -> SafetyLayer:
    return SafetyLayer(SafetyLimits(max_linear=0.8, max_angular=1.2))


def test_command_within_limits_is_unchanged(layer: SafetyLayer) -> None:
    command = layer.validate(0.5, -0.25)
    assert command.linear == 0.5
    assert command.angular == -0.25
    assert command.is_stop is False


def test_linear_is_clamped_to_max(layer: SafetyLayer) -> None:
    command = layer.validate(5.0, 0.0)
    assert command.linear == 0.8


def test_angular_is_clamped_to_max(layer: SafetyLayer) -> None:
    command = layer.validate(0.0, -9.0)
    assert command.angular == -1.2


def test_zero_command_is_a_stop(layer: SafetyLayer) -> None:
    assert layer.validate(0.0, 0.0).is_stop is True


@pytest.mark.parametrize(
    "linear, angular",
    [(math.nan, 0.0), (0.0, math.nan), (math.inf, 0.0), (0.0, -math.inf)],
)
def test_non_finite_values_are_rejected(layer: SafetyLayer, linear: float, angular: float) -> None:
    with pytest.raises(InvalidMotionCommandError):
        layer.validate(linear, angular)
