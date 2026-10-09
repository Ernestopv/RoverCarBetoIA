"""Rover service.

The service is the only entry point used by the API. It wires the safety layer,
the rover implementation and the watchdog together, and it guarantees that a
motion command can never remain active indefinitely.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.core.exceptions import RoverError
from app.rover.interface import Rover
from app.rover.models import RoverStatus
from app.rover.safety import SafetyLayer

logger = logging.getLogger(__name__)


class RoverService:
    """Coordinates safety, motion and the rover connection."""

    def __init__(
        self,
        rover: Rover,
        safety: SafetyLayer,
        *,
        command_timeout: float,
        watchdog_interval: float = 0.1,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command_timeout must be > 0")
        if watchdog_interval <= 0:
            raise ValueError("watchdog_interval must be > 0")

        self._rover = rover
        self._safety = safety
        self._command_timeout = command_timeout
        self._watchdog_interval = watchdog_interval
        self._deadline: float | None = None
        self._watchdog_task: asyncio.Task[None] | None = None

    @property
    def rover(self) -> Rover:
        return self._rover

    @property
    def safety(self) -> SafetyLayer:
        return self._safety

    # --- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Connect to the rover and start the watchdog."""
        await self._rover.connect()
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="rover-watchdog")

    async def shutdown(self) -> None:
        """Stop the rover safely and release the connection."""
        await self._cancel_watchdog()
        await self._safe_stop(reason="shutdown")
        await self._rover.disconnect()

    # --- Commands ------------------------------------------------------------

    async def move(self, linear: float, angular: float) -> RoverStatus:
        """Validate, apply and arm the watchdog for a motion command."""
        command = self._safety.validate(linear, angular)

        try:
            await self._rover.move(command)
        except RoverError:
            self._deadline = None
            logger.exception("Motion command failed linear=%.3f angular=%.3f", linear, angular)
            raise

        # A stop command disarms the watchdog; any other command arms it.
        self._deadline = None if command.is_stop else self._now() + self._command_timeout
        return await self.status()

    async def stop(self) -> RoverStatus:
        """Stop the rover. This must always succeed from the caller's view."""
        self._deadline = None
        await self._safe_stop(reason="stop command")
        return await self.status()

    async def status(self) -> RoverStatus:
        return await self._rover.status()

    # --- Internals -----------------------------------------------------------

    async def _safe_stop(self, *, reason: str) -> None:
        """Best-effort stop: never propagate an error to the caller."""
        try:
            await self._rover.stop()
        except RoverError as exc:
            logger.warning("STOP could not be confirmed (%s): %s", reason, exc)

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(self._watchdog_interval)
            deadline = self._deadline
            if deadline is None or self._now() < deadline:
                continue
            self._deadline = None
            logger.warning(
                "Watchdog: no motion command for %.2fs, stopping rover", self._command_timeout
            )
            await self._safe_stop(reason="watchdog")

    async def _cancel_watchdog(self) -> None:
        task = self._watchdog_task
        self._watchdog_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()
