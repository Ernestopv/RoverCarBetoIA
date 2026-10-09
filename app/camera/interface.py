"""Abstract camera contract.

Every camera implementation (simulator, IMX500) must obey this contract, so the
rest of the application never depends on a concrete video source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class CameraStatus(BaseModel):
    """Snapshot of the video source.

    ``stream_path`` and ``webrtc_port`` are what the browser needs to build its
    WHEP URL. The full URL is **not** returned by the backend on purpose: from
    inside the container the MediaMTX host is a Docker service name, which the
    browser cannot resolve. The frontend combines these values with its own
    hostname instead.
    """

    mode: str
    running: bool = False
    width: int
    height: int
    fps: int
    stream_path: str
    webrtc_port: int
    restarts: int = 0
    # Name of the neural network loaded in the camera, when it has one.
    model: str | None = None
    last_error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Camera(ABC):
    """High-level interface to the video source."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the video source is currently publishing."""

    @abstractmethod
    async def start(self) -> None:
        """Start the live stream.

        Must never write images or video to disk: camera media is ephemeral.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the live stream and release the video source."""

    @abstractmethod
    async def status(self) -> CameraStatus:
        """Return the current camera status."""
