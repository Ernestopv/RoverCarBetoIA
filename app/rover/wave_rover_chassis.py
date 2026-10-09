"""Transport-agnostic WAVE ROVER chassis logic.

Everything here is shared by the Wi-Fi and the serial transports:

- the pure protocol helpers (differential mixing, battery curve, charge-state
  inference, feedback parsing);
- the driver state machine (connection state, last command, latency, battery and
  charge tracking) and the :class:`Rover` contract.

A concrete transport only has to implement :meth:`WaveRoverChassisDriver._open`,
:meth:`~WaveRoverChassisDriver._close` and
:meth:`~WaveRoverChassisDriver._request`: send one JSON command and return the
decoded reply. That keeps the mapping, safety and API layers untouched whichever
wire is used.

Protocol facts, from the official Waveshare wiki and confirmed by reading the
device (see ``docs/specs/wave-rover.md``):

- ``{"T":1,"L":<left>,"R":<right>}`` — CMD_SPEED_CTRL, the recommended motion
  command. Wheel speeds are in ``-0.5..+0.5``; for this chassis (no encoders)
  ``0.5`` is 100% PWM.
- ``{"T":130}`` — CMD_BASE_FEEDBACK, answers ``T:1001`` with wheel speeds,
  attitude, temperature, voltage and current.
- The chassis has its own **3-second heartbeat**: with no new motion command it
  stops by itself. Our watchdog stops it sooner, but that is a second,
  independent safety net that keeps working if the Raspberry Pi dies.
"""

from __future__ import annotations

import json
import logging
import time
from abc import abstractmethod
from collections import deque
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import DEFAULT_BATTERY_CURVE
from app.core.exceptions import RoverConnectionError, RoverProtocolError, RoverTimeoutError
from app.rover.interface import Rover
from app.rover.models import ChargeState, ConnectionState, MotionCommand, Pose, RoverStatus

logger = logging.getLogger(__name__)

# Protocol constants, from the official command set.
CMD_SPEED_CTRL = 1
CMD_BASE_FEEDBACK = 130
CMD_SET_SPD_RATE = 138
CMD_GET_SPD_RATE = 139
RESP_BASE_FEEDBACK = 1001
RESP_IMU = 1002

#: Commands whose reply the caller needs (a plain motion command may not answer).
REPLY_COMMANDS = frozenset({CMD_BASE_FEEDBACK, CMD_GET_SPD_RATE})

#: Wheel speeds accepted by CMD_SPEED_CTRL.
PROTOCOL_MAX_SPEED = 0.5

#: How many voltage readings the rolling mean keeps. At one reading per second
#: this is roughly eight seconds of history: enough to absorb the load ripple
#: without hiding a real, gradual discharge.
_VOLTAGE_SAMPLES = 8


# --- Pure protocol helpers ---------------------------------------------------


def mix_differential(
    linear: float,
    angular: float,
    max_speed: float,
    left_trim: float = 1.0,
    right_trim: float = 1.0,
) -> tuple[float, float]:
    """Turn a normalised (linear, angular) command into left/right wheel speeds.

    Both inputs are in ``-1..1``. `angular` is positive to the left, so a left
    turn slows the left wheel: ``left = linear - angular``.

    ``left_trim`` / ``right_trim`` are per-wheel gains applied **after** the
    normalisation. Real motors never turn at exactly the same speed, so a chassis
    that veers while being commanded straight is corrected here, with
    configuration, instead of by bending the mixing maths. ``1.0`` means no
    correction.
    """
    left = linear - angular
    right = linear + angular

    # Preserve the ratio of the command while fitting the protocol's range.
    biggest = max(abs(left), abs(right), 1.0)
    scale = max_speed / biggest

    return (
        _clamp(left * scale * left_trim, max_speed),
        _clamp(right * scale * right_trim, max_speed),
    )


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def battery_percentage(
    voltage: float,
    curve: Sequence[tuple[float, float]],
) -> float:
    """Charge level from pack voltage, through the discharge curve.

    The chassis reports volts, not a percentage. A straight line between the pack
    bounds is a poor model for Li-ion: the voltage is almost flat in the middle of
    the discharge and falls steeply at the end, so the linear map overstates the
    charge for most of the run and, worse, hides a nearly dead pack.

    ``curve`` is a list of ``(voltage, percent)`` points; the answer is the
    piecewise-linear interpolation between them, clamped to the endpoints. Tested
    against ``DEFAULT_BATTERY_CURVE`` (3S Li-ion).
    """
    points = sorted(curve)

    if len(points) == 0:
        return 0.0
    if voltage <= points[0][0]:
        return points[0][1]
    if voltage >= points[-1][0]:
        return points[-1][1]

    for (low_v, low_pct), (high_v, high_pct) in zip(points, points[1:], strict=False):
        if low_v <= voltage <= high_v:
            span = high_v - low_v
            if span <= 0:
                return low_pct
            ratio = (voltage - low_v) / span
            return round(low_pct + ratio * (high_pct - low_pct), 1)

    return points[-1][1]


#: A voltage move steeper than this counts as plug/unplug. Measured on the unit:
#: plugging or unplugging moved the pack voltage ~0.25 V in seconds (~1500 mV/min),
#: while the smoothed idle ripple is tens of millivolts and even the idle drain is
#: only ~20 mV/min. The threshold sits far above both, so it only fires on real
#: charger events.
CHARGE_SLOPE_THRESHOLD_MV_PER_MIN = 150.0

#: The trend is ignored until the window has this much history and this many
#: samples, so the short, noisy windows right after start cannot decide anything.
CHARGE_MIN_WINDOW_SECONDS = 60.0
CHARGE_MIN_SAMPLES = 30

#: How much history (seconds) the voltage trend is measured over.
CHARGE_TREND_WINDOW_SECONDS = 120.0


def next_charge_state(slope_mv_per_min: float, state: ChargeState) -> ChargeState:
    """What the voltage trend is telling us, with hysteresis.

    A sustained rise means something is holding the voltage up — a charger.
    A sustained fall means the pack is supplying. Anything between keeps the last
    state, so the answer does not flicker while the voltage merely wanders.
    """
    if slope_mv_per_min >= CHARGE_SLOPE_THRESHOLD_MV_PER_MIN:
        return ChargeState.CHARGING
    if slope_mv_per_min <= -CHARGE_SLOPE_THRESHOLD_MV_PER_MIN:
        return ChargeState.DISCHARGING
    return state


class ChassisFeedback(BaseModel):
    """Decoded ``CMD_BASE_FEEDBACK`` response (``T:1001``)."""

    model_config = ConfigDict(extra="ignore")

    wheel_left: float = 0.0
    wheel_right: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    temperature_c: float | None = None
    voltage_v: float | None = None
    current_ma: float | None = None
    overvoltage: bool = False


def parse_chassis_feedback(payload: dict) -> ChassisFeedback:
    """Decode the chassis feedback payload, tolerating missing optional fields."""
    if payload.get("T") != RESP_BASE_FEEDBACK:
        raise RoverProtocolError(f"Unexpected feedback type: {payload.get('T')!r}")

    return ChassisFeedback(
        wheel_left=float(payload.get("L", 0.0)),
        wheel_right=float(payload.get("R", 0.0)),
        roll=float(payload.get("r", 0.0)),
        pitch=float(payload.get("p", 0.0)),
        yaw=float(payload.get("y", 0.0)),
        temperature_c=payload.get("temp"),
        voltage_v=payload.get("v"),
        current_ma=payload.get("c"),
        overvoltage=bool(payload.get("ov", False)),
    )


class SpeedCommand(BaseModel):
    """Body of CMD_SPEED_CTRL."""

    t: int = Field(default=CMD_SPEED_CTRL, alias="T")
    left: float = Field(default=0.0, alias="L")
    right: float = Field(default=0.0, alias="R")

    model_config = ConfigDict(populate_by_name=True)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(by_alias=True))


# --- Base driver -------------------------------------------------------------


class WaveRoverChassisDriver(Rover):
    """Shared behaviour of every WAVE ROVER transport.

    Subclasses implement the wire: :meth:`_open`, :meth:`_close` and
    :meth:`_request`. Everything else — connection state, motion mapping, battery
    and charge inference, the watchdog-visible command state — lives here.
    """

    def __init__(
        self,
        *,
        transport: str,
        source: str,
        timeout: float,
        max_speed: float = PROTOCOL_MAX_SPEED,
        battery_curve: Sequence[tuple[float, float]] = DEFAULT_BATTERY_CURVE,
        speed_rate: float = 1.0,
        left_trim: float = 1.0,
        right_trim: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._source = source
        self._timeout = timeout
        self._max_speed = min(max_speed, PROTOCOL_MAX_SPEED)
        self._battery_curve = battery_curve
        # The chassis's voltage wavers by tens of millivolts with the load; a
        # short rolling mean shows the real trend instead of the ripple.
        self._voltage_samples: deque[float] = deque(maxlen=_VOLTAGE_SAMPLES)
        # Charger inference: the voltage trend and the latched verdict.
        self._charge_samples: deque[tuple[float, float]] = deque()
        self._charge_state = ChargeState.UNKNOWN
        # Injectable so tests can advance the trend window without sleeping.
        self._clock = clock
        self._want_speed_rate = speed_rate
        self._left_trim = left_trim
        self._right_trim = right_trim

        self._state = ConnectionState.DISCONNECTED
        self._command = MotionCommand()
        self._feedback: ChassisFeedback | None = None
        self._latency_ms: float | None = None
        self._last_command_at: float | None = None
        self._last_error: str | None = None

    # --- Rover contract ------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True unless the driver was explicitly disconnected.

        A failed request is *reported* through the state and `last_error`, but it
        must never wedge the driver: the next request is still attempted, and a
        success restores ``CONNECTED`` again.

        Making a failure sticky is a trap: one timeout would leave the rover
        uncontrollable until the process restarted, which is exactly what
        happened during the first hardware test (every later command answered
        503).
        """
        return self._state is not ConnectionState.DISCONNECTED

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTING
        logger.info("Connecting to WAVE ROVER over %s (%s)", self._transport, self._source)

        try:
            await self._open()
            # Ask for the chassis feedback: it proves the link answers and gives
            # us a first real reading.
            await self._request({"T": CMD_BASE_FEEDBACK}, parse_feedback=True)
        except Exception:
            self._state = ConnectionState.ERROR
            raise

        self._state = ConnectionState.CONNECTED
        await self._ensure_speed_rate()

        logger.info(
            "WAVE ROVER connected over %s (%.0f mV, %.1f C)",
            self._transport,
            (self._feedback.voltage_v or 0) * 1000 if self._feedback else 0,
            (self._feedback.temperature_c or 0) if self._feedback else 0,
        )

    async def disconnect(self) -> None:
        self._command = MotionCommand()
        try:
            await self._close()
        finally:
            self._state = ConnectionState.DISCONNECTED
        logger.info("WAVE ROVER disconnected (%s)", self._transport)

    async def move(self, command: MotionCommand) -> None:
        self._ensure_connected()
        left, right = mix_differential(
            command.linear,
            command.angular,
            self._max_speed,
            left_trim=self._left_trim,
            right_trim=self._right_trim,
        )
        await self._send_speed(left, right)
        self._command = command

    async def stop(self) -> None:
        # The chassis stops by itself after 3 s without commands, but a stop must
        # be immediate and explicit. Local state is cleared even if the request
        # fails, so we never keep a motion command active on our side.
        self._command = MotionCommand()
        self._ensure_connected()
        await self._send_speed(0.0, 0.0)

    async def status(self) -> RoverStatus:
        # Refresh from the chassis when we can; fall back to the last reading so
        # a transient failure does not blank the operator's screen.
        try:
            await self._request({"T": CMD_BASE_FEEDBACK}, parse_feedback=True)
        except (RoverConnectionError, RoverTimeoutError, RoverProtocolError) as exc:
            logger.warning("Could not refresh WAVE ROVER status: %s", exc)

        feedback = self._feedback
        voltage = self._smoothed_voltage(feedback.voltage_v) if feedback else None
        return RoverStatus(
            connection=self._state,
            moving=not self._command.is_stop,
            linear=self._command.linear,
            angular=self._command.angular,
            pose=Pose(
                heading=(feedback.yaw if feedback else 0.0),
                # The chassis gives roll/pitch/yaw, not x/y: it has no encoders,
                # so there is no odometry to integrate.
            ),
            battery_voltage=voltage,
            battery_current_ma=feedback.current_ma if feedback else None,
            battery_charge_state=self._consider_charge_state(voltage),
            battery_percentage=(
                battery_percentage(voltage, self._battery_curve) if voltage is not None else None
            ),
            latency_ms=self._latency_ms,
            last_command_age_s=(
                round(time.monotonic() - self._last_command_at, 3)
                if self._last_command_at is not None
                else None
            ),
        )

    # --- Internals -----------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise RoverConnectionError("WAVE ROVER is not connected")

    def _smoothed_voltage(self, voltage: float | None) -> float | None:
        """Rolling mean of the pack voltage.

        The chassis's reading wavers by tens of millivolts with the load, which
        would make a percentage bounce around without meaning. Averaging shows the
        gradual, real trend instead of the ripple.
        """
        if voltage is None:
            return None
        self._voltage_samples.append(float(voltage))
        return round(sum(self._voltage_samples) / len(self._voltage_samples), 3)

    def _consider_charge_state(self, voltage: float | None) -> ChargeState:
        """Update the inferred charger state from the smoothed voltage trend.

        A steep, sustained rise means something is holding the voltage up — a
        charger. A steep, sustained fall means the pack is supplying. Everything
        else (idle ripple, the slow drain of normal operation) keeps the last
        verdict instead of flickering.

        The trend is only judged once the window has real history: right after
        start the window is short and noisy, and a fresh driver must not decide
        anything on it.
        """
        if voltage is None:
            return self._charge_state

        now = self._clock()
        self._charge_samples.append((now, float(voltage)))
        while (
            self._charge_samples and now - self._charge_samples[0][0] > CHARGE_TREND_WINDOW_SECONDS
        ):
            self._charge_samples.popleft()

        if len(self._charge_samples) < CHARGE_MIN_SAMPLES:
            return self._charge_state

        (first_time, first_voltage), (last_time, last_voltage) = (
            self._charge_samples[0],
            self._charge_samples[-1],
        )
        span = last_time - first_time
        if span < CHARGE_MIN_WINDOW_SECONDS:
            return self._charge_state

        slope_mv_per_min = (last_voltage - first_voltage) / span * 60_000
        self._charge_state = next_charge_state(slope_mv_per_min, self._charge_state)
        return self._charge_state

    async def _send_speed(self, left: float, right: float) -> None:
        command = SpeedCommand(left=round(left, 4), right=round(right, 4))
        await self._request(json.loads(command.to_json()), parse_feedback=False)
        self._last_command_at = time.monotonic()

    async def _ensure_speed_rate(self) -> None:
        """Make sure the chassis is actually allowed to move.

        The factory ``boot.mission`` on this unit sets the speed rate to 0 on
        every power-up, and with a rate of 0 the chassis ignores every motion
        command. A non-zero rate is left alone, so a value chosen by hand in the
        chassis web UI is respected.

        Caveat: a rate of 0 moves nothing, and a *low* rate moves weakly.
        """
        reply = await self._request({"T": CMD_GET_SPD_RATE}, parse_feedback=False)
        if not isinstance(reply, dict):
            return

        current = (reply.get("L", 0), reply.get("R", 0))
        if current != (0, 0):
            logger.info("WAVE ROVER speed rate already set to %s", current)
            return

        logger.warning(
            "WAVE ROVER speed rate is 0: the chassis would ignore every motion command. "
            "Setting it to %.2f",
            self._want_speed_rate,
        )
        await self._request(
            {
                "T": CMD_SET_SPD_RATE,
                "L": self._want_speed_rate,
                "R": self._want_speed_rate,
            },
            parse_feedback=False,
        )

    def _record_ok(self, *, started: float) -> None:
        self._latency_ms = round((time.monotonic() - started) * 1000, 1)
        # Any answer proves the chassis is there: recover automatically.
        self._state = ConnectionState.CONNECTED
        self._last_error = None

    def _record_error(
        self, exc: Exception, *, state: ConnectionState = ConnectionState.ERROR
    ) -> None:
        self._state = state
        self._last_error = str(exc)

    # --- Transport, implemented by subclasses --------------------------------

    @abstractmethod
    async def _open(self) -> None:
        """Open the link. Raise :class:`RoverConnectionError` on failure."""

    @abstractmethod
    async def _close(self) -> None:
        """Close the link. Must be safe to call more than once."""

    @abstractmethod
    async def _request(self, command: dict, *, parse_feedback: bool) -> dict | None:
        """Send one JSON command and return the decoded reply.

        Raise :class:`RoverTimeoutError` when a reply was required and none
        arrived, and :class:`RoverConnectionError` on a transport failure.
        """
