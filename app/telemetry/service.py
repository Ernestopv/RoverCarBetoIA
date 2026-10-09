"""Telemetry service.

Telemetry is read-only and optional: sensors that are not available simply
report ``None``. Nothing here writes images, video or any ephemeral camera
data to disk.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.ai.detection import DetectionService
from app.rover.interface import Rover
from app.rover.models import RoverStatus

logger = logging.getLogger(__name__)

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


class TelemetrySnapshot(BaseModel):
    """Best-effort snapshot of the rover and host state."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    rover: RoverStatus
    cpu_temperature_c: float | None = None
    #: Time the sensor spent on the last inference (DNN + DSP).
    ai_inference_ms: float | None = None
    #: Objects reported by the last inference, if the camera has a network.
    detections: int | None = None


def read_cpu_temperature() -> float | None:
    """Read the SoC temperature in Celsius, or ``None`` when unavailable."""
    try:
        raw = _THERMAL_ZONE.read_text(encoding="ascii").strip()
    except OSError:
        # Not a Raspberry Pi, or the kernel does not expose a thermal zone.
        return None
    try:
        return round(int(raw) / 1000.0, 1)
    except ValueError:
        logger.warning("Unexpected thermal zone content: %r", raw)
        return None


class TelemetryService:
    """Collects a telemetry snapshot from the rover and, if present, the AI."""

    def __init__(self, rover: Rover, detections: DetectionService | None = None) -> None:
        self._rover = rover
        self._detections = detections

    async def snapshot(self) -> TelemetrySnapshot:
        detect = self._detections.snapshot() if self._detections is not None else None

        return TelemetrySnapshot(
            rover=await self._rover.status(),
            cpu_temperature_c=read_cpu_temperature(),
            ai_inference_ms=detect.inference_ms if detect else None,
            detections=len(detect.detections) if detect and detect.available else None,
        )
