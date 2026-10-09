"""Tests for the simulated rover."""

from __future__ import annotations

import pytest

from app.core.exceptions import RoverConnectionError, RoverTimeoutError
from app.rover.models import ConnectionState, MotionCommand
from app.rover.simulator import WaveRoverSimulator


async def test_starts_disconnected() -> None:
    rover = WaveRoverSimulator()
    assert rover.is_connected is False
    assert (await rover.status()).connection is ConnectionState.DISCONNECTED


async def test_connect_and_disconnect() -> None:
    rover = WaveRoverSimulator()
    await rover.connect()
    assert rover.is_connected is True
    assert (await rover.status()).connection is ConnectionState.CONNECTED

    await rover.disconnect()
    assert rover.is_connected is False


async def test_move_requires_connection() -> None:
    rover = WaveRoverSimulator()
    with pytest.raises(RoverConnectionError):
        await rover.move(MotionCommand(linear=0.5, angular=0.0))


async def test_move_then_stop_updates_status() -> None:
    rover = WaveRoverSimulator()
    await rover.connect()

    await rover.move(MotionCommand(linear=0.5, angular=0.2))
    moving = await rover.status()
    assert moving.moving is True
    assert moving.linear == 0.5
    assert moving.angular == 0.2

    await rover.stop()
    stopped = await rover.status()
    assert stopped.moving is False
    assert stopped.linear == 0.0
    assert stopped.angular == 0.0


async def test_link_loss_clears_motion_and_state() -> None:
    rover = WaveRoverSimulator()
    await rover.connect()
    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    rover.simulate_link_loss()

    status = await rover.status()
    assert status.connection is ConnectionState.DISCONNECTED
    assert status.moving is False


async def test_simulated_failure_raises_timeout() -> None:
    rover = WaveRoverSimulator(failure_rate=1.0)
    await rover.connect()
    with pytest.raises(RoverTimeoutError):
        await rover.move(MotionCommand(linear=0.5, angular=0.0))


async def test_battery_drains_while_moving() -> None:
    clock_value = {"now": 0.0}
    rover = WaveRoverSimulator(clock=lambda: clock_value["now"])
    await rover.connect()

    before = (await rover.status()).battery_percentage
    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    clock_value["now"] += 10.0
    after = (await rover.status()).battery_percentage

    assert before is not None and after is not None
    assert after < before


async def test_pose_advances_when_moving() -> None:
    clock_value = {"now": 0.0}
    rover = WaveRoverSimulator(clock=lambda: clock_value["now"])
    await rover.connect()
    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    clock_value["now"] += 1.0
    status = await rover.status()

    assert status.pose.x > 0.0


async def test_invalid_latency_is_rejected() -> None:
    with pytest.raises(ValueError):
        WaveRoverSimulator(latency=-1.0)

    with pytest.raises(ValueError):
        WaveRoverSimulator(failure_rate=2.0)
