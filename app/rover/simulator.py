"""Simulated WAVE ROVER.

The simulator is a first-class part of the project, not a temporary stub. It
must behave like the expected rover well enough to develop and test the whole
backend without risk, including latency, failures and link loss.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable

from app.core.exceptions import RoverConnectionError, RoverTimeoutError
from app.rover.interface import Rover
from app.rover.models import ConnectionState, MotionCommand, Pose, RoverStatus

logger = logging.getLogger(__name__)

# Virtual differential-drive model. With ``linear == 1`` the rover moves at
# ``_SPEED_AT_FULL_SCALE`` m/s and turns at ``_TURN_AT_FULL_SCALE`` rad/s.
_SPEED_AT_FULL_SCALE = 0.6
_TURN_AT_FULL_SCALE = 1.2
# Battery points consumed per second while driving at ``linear == 1``.
_BATTERY_DRAIN_PER_SECOND = 0.05
# 2S LiPo pack voltage range used to derive a plausible voltage reading.
_BATTERY_MIN_VOLTAGE = 6.0
_BATTERY_MAX_VOLTAGE = 8.4


class WaveRoverSimulator(Rover):
    """In-memory implementation of the :class:`Rover` contract."""

    def __init__(
        self,
        *,
        latency: float = 0.0,
        failure_rate: float = 0.0,
        initial_battery_percentage: float = 100.0,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        if latency < 0:
            raise ValueError("latency must be >= 0")
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be in [0, 1]")

        self._latency = latency
        self._failure_rate = failure_rate
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()

        self._state = ConnectionState.DISCONNECTED
        self._command = MotionCommand()
        self._pose = Pose()
        self._battery = max(0.0, min(100.0, initial_battery_percentage))
        self._last_update = self._clock()
        self._last_command_at: float | None = None

    # --- Rover contract ------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTING
        logger.info("Simulator connecting")
        await self._apply_latency()
        self._state = ConnectionState.CONNECTED
        self._last_update = self._clock()
        logger.info("Simulator connected")

    async def disconnect(self) -> None:
        self._command = MotionCommand()
        await self._apply_latency()
        self._state = ConnectionState.DISCONNECTED
        logger.info("Simulator disconnected")

    async def move(self, command: MotionCommand) -> None:
        self._ensure_connected()
        await self._apply_latency_and_failures(operation="move")
        self._integrate()
        self._command = command
        self._last_command_at = self._clock()
        logger.debug("Simulator move linear=%.3f angular=%.3f", command.linear, command.angular)

    async def stop(self) -> None:
        # Local state is cleared first: even if the link is lost the simulator
        # must never keep a motion command active.
        self._command = MotionCommand()
        self._last_command_at = self._clock()
        self._ensure_connected()
        await self._apply_latency_and_failures(operation="stop")
        logger.debug("Simulator stopped")

    async def status(self) -> RoverStatus:
        self._integrate()
        return RoverStatus(
            connection=self._state,
            moving=not self._command.is_stop,
            linear=self._command.linear,
            angular=self._command.angular,
            pose=self._pose.model_copy(),
            battery_percentage=round(self._battery, 2),
            battery_voltage=self._voltage(),
            latency_ms=self._latency * 1000.0 if self._latency else 0.0,
            last_command_age_s=self._command_age(),
        )

    # --- Test / simulation helpers ------------------------------------------

    def simulate_link_loss(self) -> None:
        """Drop the link and clear any active motion command."""
        logger.warning("Simulator link lost")
        self._state = ConnectionState.DISCONNECTED
        self._command = MotionCommand()

    def simulate_incoming_failure(self) -> None:
        """Force the next network operation to time out."""
        self._failure_rate = 1.0

    # --- Internals -----------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise RoverConnectionError("Rover is not connected")

    async def _apply_latency(self) -> None:
        if self._latency > 0:
            await asyncio.sleep(self._latency)

    async def _apply_latency_and_failures(self, *, operation: str) -> None:
        await self._apply_latency()
        if self._rng.random() < self._failure_rate:
            raise RoverTimeoutError(f"Simulated timeout during '{operation}'")

    def _integrate(self) -> None:
        now = self._clock()
        elapsed = now - self._last_update
        self._last_update = now
        if elapsed <= 0:
            return

        linear = self._command.linear
        angular = self._command.angular

        self._pose.heading += angular * _TURN_AT_FULL_SCALE * elapsed
        speed = linear * _SPEED_AT_FULL_SCALE
        self._pose.x += speed * math.cos(self._pose.heading) * elapsed
        self._pose.y += speed * math.sin(self._pose.heading) * elapsed

        if not self._command.is_stop:
            drain = _BATTERY_DRAIN_PER_SECOND * abs(linear) * elapsed
            self._battery = max(0.0, self._battery - drain)

    def _voltage(self) -> float:
        span = _BATTERY_MAX_VOLTAGE - _BATTERY_MIN_VOLTAGE
        return round(_BATTERY_MIN_VOLTAGE + (self._battery / 100.0) * span, 2)

    def _command_age(self) -> float | None:
        if self._last_command_at is None:
            return None
        return round(self._clock() - self._last_command_at, 3)
