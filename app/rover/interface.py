"""Abstract rover contract.

Every rover implementation (simulator, Wi-Fi driver, future hardware) must obey
this contract so the rest of the application never depends on a concrete
implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.rover.models import MotionCommand, RoverStatus


class Rover(ABC):
    """High-level interface to the motor base."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the rover can currently accept commands."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the link with the motor base.

        Must raise :class:`app.core.exceptions.RoverConnectionError` on failure.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Release the link. The rover is stopped first when possible."""

    @abstractmethod
    async def move(self, command: MotionCommand) -> None:
        """Apply a motion command.

        The command is already validated and clamped by the safety layer.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Bring the rover to a halt immediately."""

    @abstractmethod
    async def status(self) -> RoverStatus:
        """Return the current rover status."""
