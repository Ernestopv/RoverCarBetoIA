"""WAVE ROVER serial (UART) driver.

Talks to the chassis over the **40-pin header UART** at 115200
(``/dev/ttyAMA0``), which is the official method in the Waveshare wiki: the
chassis routes its UART to the header, where this Raspberry Pi is already
mounted, so **no extra cabling is needed**.

The protocol is identical to the Wi-Fi transport: newline-delimited JSON
commands (``{"T":1,"L":..,"R":..}`` for motion, ``{"T":130}`` for feedback) and
``{"T":1001,...}`` feedback lines. Everything the two share lives in
:mod:`app.rover.wave_rover_chassis`; this module only implements the *wire*.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from threading import Lock

from app.core.config import DEFAULT_BATTERY_CURVE
from app.core.exceptions import RoverConnectionError, RoverTimeoutError
from app.rover.models import ConnectionState
from app.rover.wave_rover_chassis import (
    PROTOCOL_MAX_SPEED,
    REPLY_COMMANDS,
    WaveRoverChassisDriver,
    parse_chassis_feedback,
)

try:
    import serial  # pyserial
except ImportError as exc:  # pragma: no cover - depends on the deployment
    serial = None  # type: ignore[assignment]
    _SERIAL_IMPORT_ERROR = exc
else:
    _SERIAL_IMPORT_ERROR = None

logger = logging.getLogger(__name__)

DEFAULT_SERIAL_PORT = "/dev/ttyAMA0"
SERIAL_BAUD = 115200


class WaveRoverSerialDriver(WaveRoverChassisDriver):
    """Remote control of the WAVE ROVER chassis over the header UART."""

    def __init__(
        self,
        *,
        port: str = DEFAULT_SERIAL_PORT,
        baudrate: int = SERIAL_BAUD,
        timeout: float = 1.0,
        max_speed: float = PROTOCOL_MAX_SPEED,
        battery_curve: Sequence[tuple[float, float]] = DEFAULT_BATTERY_CURVE,
        speed_rate: float = 1.0,
        left_trim: float = 1.0,
        right_trim: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            transport="serial",
            source=f"{port}@{baudrate}",
            timeout=timeout,
            max_speed=max_speed,
            battery_curve=battery_curve,
            speed_rate=speed_rate,
            left_trim=left_trim,
            right_trim=right_trim,
            clock=clock,
        )
        self._port = port
        self._baudrate = baudrate
        self._ser: serial.Serial | None = None
        self._lock = Lock()

    # --- Transport -----------------------------------------------------------

    async def _open(self) -> None:
        if _SERIAL_IMPORT_ERROR is not None:
            raise RoverConnectionError(
                "pyserial is not installed (add it to requirements.txt)"
            ) from _SERIAL_IMPORT_ERROR

        def _open_port() -> serial.Serial:
            handle = serial.Serial(
                self._port,
                self._baudrate,
                timeout=0.1,
                write_timeout=1.0,
            )
            handle.reset_input_buffer()
            return handle

        try:
            self._ser = await asyncio.to_thread(_open_port)
        except Exception as exc:  # noqa: BLE001 - the message is what the operator sees
            raise RoverConnectionError(f"Could not open serial port {self._port}: {exc}") from exc

    async def _close(self) -> None:
        handle, self._ser = self._ser, None
        if handle is not None:
            try:
                await asyncio.to_thread(handle.close)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not close serial port: %s", exc)

    async def _request(self, command: dict, *, parse_feedback: bool) -> dict | None:
        if self._ser is None:
            raise RoverConnectionError("Serial port is not open")
        # pyserial blocks; keep the event loop free.
        return await asyncio.to_thread(self._request_blocking, command, parse_feedback)

    def _request_blocking(self, command: dict, parse_feedback: bool) -> dict | None:
        """One blocking request/response exchange, safe to call from a thread."""
        needs_reply = command.get("T") in REPLY_COMMANDS
        started = time.monotonic()
        try:
            with self._lock:
                # Drop anything left over from a previous exchange.
                self._ser.reset_input_buffer()
                self._ser.write((json.dumps(command) + "\n").encode("utf-8"))
                self._ser.flush()

                if not needs_reply:
                    # Motion commands need no answer: return as soon as they are
                    # sent (the Wi-Fi transport behaves the same). Dropping the
                    # pending echo keeps it from being mistaken for a reply by
                    # the next status query.
                    self._record_ok(started=started)
                    return None

                reply: dict | None = None
                deadline = started + self._timeout
                while time.monotonic() < deadline:
                    line = self._ser.readline()
                    if not line:
                        continue
                    text = line.decode("utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    try:
                        candidate = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(candidate, dict) and "T" in candidate:
                        # The chassis echoes the received command back before the
                        # real reply; skip the echo, never treat it as a reply.
                        if candidate == command:
                            continue
                        reply = candidate
                        break
        except Exception as exc:  # noqa: BLE001 - the message is what the operator sees
            self._record_error(exc)
            raise RoverConnectionError(f"Serial command failed on {self._port}: {exc}") from exc

        self._record_ok(started=started)

        if reply is None:
            self._record_error(TimeoutError(), state=ConnectionState.ERROR)
            raise RoverTimeoutError(
                f"WAVE ROVER did not answer on {self._port} in {self._timeout}s"
            )

        if parse_feedback:
            self._feedback = parse_chassis_feedback(reply)
        return reply
