"""Tests for configuration and the rover factory."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.rover.factory import create_rover, create_safety_layer
from app.rover.simulator import WaveRoverSimulator
from app.rover.wave_rover_wifi import WaveRoverWifiDriver


def test_defaults_are_simulator_friendly() -> None:
    settings = Settings(_env_file=None)
    assert settings.rover_mode == "simulator"
    assert settings.camera_mode == "simulator"
    assert settings.is_simulator is True


def test_log_level_is_normalized() -> None:
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rover_mode="spaceship")


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_linear_speed=0)


def test_factory_builds_simulator() -> None:
    settings = Settings(_env_file=None, rover_mode="simulator")
    assert isinstance(create_rover(settings), WaveRoverSimulator)


def test_factory_builds_the_hardware_driver() -> None:
    settings = Settings(
        _env_file=None,
        rover_mode="hardware",
        wave_rover_host="192.168.4.1",
        wave_rover_port=80,
    )

    rover = create_rover(settings)

    assert isinstance(rover, WaveRoverWifiDriver)


def test_factory_applies_safety_limits() -> None:
    settings = Settings(_env_file=None, max_linear_speed=0.3, max_angular_speed=0.7)
    limits = create_safety_layer(settings).limits
    assert limits.max_linear == 0.3
    assert limits.max_angular == 0.7
