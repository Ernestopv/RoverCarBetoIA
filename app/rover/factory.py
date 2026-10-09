"""Rover factory.

Selects the rover implementation from configuration:

- ``simulator`` (default): in-memory. Runs anywhere.
- ``hardware``: the real WAVE ROVER chassis over Wi-Fi.
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.rover.interface import Rover
from app.rover.safety import SafetyLayer, SafetyLimits
from app.rover.simulator import WaveRoverSimulator
from app.rover.wave_rover_serial import WaveRoverSerialDriver
from app.rover.wave_rover_wifi import WaveRoverWifiDriver

logger = logging.getLogger(__name__)


def create_rover(settings: Settings) -> Rover:
    """Build the rover implementation selected by the configuration."""
    if settings.rover_mode == "simulator":
        logger.info(
            "Rover mode: simulator (latency=%.2fs, failure_rate=%.2f)",
            settings.simulator_latency,
            settings.simulator_failure_rate,
        )
        return WaveRoverSimulator(
            latency=settings.simulator_latency,
            failure_rate=settings.simulator_failure_rate,
        )

    if settings.rover_mode == "hardware":
        if settings.wave_rover_transport == "serial":
            logger.info(
                "Rover mode: hardware (WAVE ROVER serial on %s)",
                settings.wave_rover_serial_port,
            )
            return WaveRoverSerialDriver(
                port=settings.wave_rover_serial_port,
                timeout=settings.wave_rover_timeout,
                max_speed=settings.wave_rover_max_speed,
                battery_curve=settings.wave_rover_battery_curve,
                speed_rate=settings.wave_rover_speed_rate,
                left_trim=settings.wave_rover_left_trim,
                right_trim=settings.wave_rover_right_trim,
            )

        logger.info(
            "Rover mode: hardware (WAVE ROVER at %s:%s)",
            settings.wave_rover_host,
            settings.wave_rover_port,
        )
        return WaveRoverWifiDriver(
            host=settings.wave_rover_host,
            port=settings.wave_rover_port,
            timeout=settings.wave_rover_timeout,
            max_speed=settings.wave_rover_max_speed,
            battery_curve=settings.wave_rover_battery_curve,
            speed_rate=settings.wave_rover_speed_rate,
            left_trim=settings.wave_rover_left_trim,
            right_trim=settings.wave_rover_right_trim,
        )

    raise ConfigurationError(f"Unsupported ROVER_MODE: {settings.rover_mode!r}")


def create_safety_layer(settings: Settings) -> SafetyLayer:
    """Build the safety layer from the configured limits."""
    return SafetyLayer(
        SafetyLimits(
            max_linear=settings.max_linear_speed,
            max_angular=settings.max_angular_speed,
        )
    )
