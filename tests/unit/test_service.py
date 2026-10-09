"""Tests for the rover service (safety + watchdog + connection handling)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import InvalidMotionCommandError, RoverConnectionError
from app.rover.models import ConnectionState
from app.rover.safety import SafetyLayer, SafetyLimits
from app.rover.service import RoverService
from app.rover.simulator import WaveRoverSimulator


async def test_move_updates_status(service: RoverService) -> None:
    await service.start()
    try:
        status = await service.move(0.5, 0.0)
        assert status.moving is True
        assert status.linear == 0.5
    finally:
        await service.shutdown()


async def test_move_without_link_raises(service: RoverService) -> None:
    await service.start()
    try:
        service.rover.simulate_link_loss()
        with pytest.raises(RoverConnectionError):
            await service.move(0.5, 0.0)
    finally:
        await service.shutdown()


async def test_stop_always_succeeds_even_without_link(service: RoverService) -> None:
    await service.start()
    try:
        service.rover.simulate_link_loss()
        status = await service.stop()
        assert status.connection is ConnectionState.DISCONNECTED
        assert status.moving is False
    finally:
        await service.shutdown()


async def test_watchdog_stops_rover_after_command_timeout(service: RoverService) -> None:
    await service.start()
    try:
        await service.move(0.6, 0.0)
        assert (await service.status()).moving is True

        await asyncio.sleep(0.2)

        assert (await service.status()).moving is False
    finally:
        await service.shutdown()


async def test_explicit_stop_disarms_watchdog(service: RoverService) -> None:
    await service.start()
    try:
        await service.move(0.6, 0.0)
        await service.stop()
        await asyncio.sleep(0.1)
        assert (await service.status()).moving is False
    finally:
        await service.shutdown()


async def test_zero_command_disarms_watchdog(service: RoverService) -> None:
    await service.start()
    try:
        status = await service.move(0.0, 0.0)
        assert status.moving is False
        await asyncio.sleep(0.1)
        assert (await service.status()).moving is False
    finally:
        await service.shutdown()


async def test_service_rejects_non_finite_command(service: RoverService) -> None:
    await service.start()
    try:
        with pytest.raises(InvalidMotionCommandError):
            await service.move(float("nan"), 0.0)
    finally:
        await service.shutdown()


async def test_start_is_idempotent() -> None:
    rover = WaveRoverSimulator()
    safety = SafetyLayer(SafetyLimits(max_linear=1.0, max_angular=1.0))
    service = RoverService(rover, safety, command_timeout=0.05)

    await service.start()
    await service.start()
    await service.shutdown()

    assert service.rover.is_connected is False
