"""Domain models shared by every rover implementation.

These models are hardware-agnostic: the simulator, the Wi-Fi driver and the
service layer all exchange the same types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConnectionState(StrEnum):
    """Explicit connection state of the motor base.

    The link is an external resource that can fail at any time, so its state is
    always modelled explicitly instead of being assumed.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class ChargeState(StrEnum):
    """What the power trend suggests about the pack.

    Inferred from voltage behaviour, not reported by the chassis: a rising
    voltage usually means a charger is holding the pack up, a falling one means
    the pack is supplying. ``unknown`` means no clear move has been observed
    since start.
    """

    UNKNOWN = "unknown"
    CHARGING = "charging"
    DISCHARGING = "discharging"


class MotionCommand(BaseModel):
    """A normalized motion command.

    ``linear`` and ``angular`` are in the ``[-1, 1]`` range before safety
    clamping. Positive ``linear`` moves forward; positive ``angular`` turns
    left (counter-clockwise).
    """

    model_config = ConfigDict(frozen=True)

    linear: float = 0.0
    angular: float = 0.0

    @property
    def is_stop(self) -> bool:
        """True when the command requests no motion at all."""
        return self.linear == 0.0 and self.angular == 0.0


class Pose(BaseModel):
    """Virtual position and orientation of the rover (simulation only)."""

    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


class RoverStatus(BaseModel):
    """Snapshot of the rover state.

    Optional fields (battery, latency) must be ``None`` when the underlying
    implementation cannot provide them.
    """

    connection: ConnectionState = ConnectionState.DISCONNECTED
    moving: bool = False
    linear: float = 0.0
    angular: float = 0.0
    pose: Pose = Field(default_factory=Pose)
    battery_voltage: float | None = None
    battery_percentage: float | None = None
    #: Pack current draw in milliamps, when the chassis reports it.
    battery_current_ma: float | None = None
    #: What the voltage trend suggests about the charger, inferred not measured.
    battery_charge_state: ChargeState = ChargeState.UNKNOWN
    latency_ms: float | None = None
    last_command_age_s: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
