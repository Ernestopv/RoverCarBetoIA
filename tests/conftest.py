"""Shared test fixtures.

Tests never touch physical hardware: they always run against the simulator.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.rover.safety import SafetyLayer, SafetyLimits
from app.rover.service import RoverService
from app.rover.simulator import WaveRoverSimulator


@pytest.fixture
def settings() -> Settings:
    """Isolated settings: no `.env`, no environment leakage."""
    return Settings(
        _env_file=None,
        rover_mode="simulator",
        camera_mode="simulator",
        # Tests never spawn a video publisher.
        camera_autostart=False,
        command_timeout=0.2,
        watchdog_interval=0.02,
        simulator_latency=0.0,
        simulator_failure_rate=0.0,
        max_linear_speed=1.0,
        max_angular_speed=1.5,
    )


@pytest.fixture
def safety() -> SafetyLayer:
    return SafetyLayer(SafetyLimits(max_linear=1.0, max_angular=1.5))


@pytest.fixture
def simulator() -> WaveRoverSimulator:
    return WaveRoverSimulator()


@pytest.fixture
def service(simulator: WaveRoverSimulator, safety: SafetyLayer) -> RoverService:
    return RoverService(
        simulator,
        safety,
        command_timeout=0.05,
        watchdog_interval=0.01,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
