"""WAVE ROVER Wi-Fi driver.

Talks to the chassis over HTTP, which is what the official documentation
describes (`GET http://<rover>/js?json={...}`), verified against the real unit.

The protocol knowledge (mixing, battery curve, charge inference, feedback
parsing) and the driver state machine live in :mod:`app.rover.wave_rover_chassis`,
shared with the serial transport. This module only implements the HTTP *wire*.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence

import httpx

from app.core.config import DEFAULT_BATTERY_CURVE
from app.core.exceptions import RoverConnectionError, RoverProtocolError, RoverTimeoutError
from app.rover.wave_rover_chassis import (
    PROTOCOL_MAX_SPEED,
    WaveRoverChassisDriver,
    battery_percentage,
    mix_differential,
    next_charge_state,
    parse_chassis_feedback,
)

logger = logging.getLogger(__name__)

_ENDPOINT = "/js"

# Backwards-compatible re-exports: the pure helpers moved to the chassis module,
# but callers and tests still import them from here.
__all__ = [
    "PROTOCOL_MAX_SPEED",
    "WaveRoverWifiDriver",
    "battery_percentage",
    "mix_differential",
    "next_charge_state",
    "parse_chassis_feedback",
]


class WaveRoverWifiDriver(WaveRoverChassisDriver):
    """Remote control of the WAVE ROVER chassis over Wi-Fi."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 80,
        timeout: float = 1.0,
        max_speed: float = PROTOCOL_MAX_SPEED,
        battery_curve: Sequence[tuple[float, float]] = DEFAULT_BATTERY_CURVE,
        speed_rate: float = 1.0,
        left_trim: float = 1.0,
        right_trim: float = 1.0,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            transport="wifi",
            source=f"{host}:{port}",
            timeout=timeout,
            max_speed=max_speed,
            battery_curve=battery_curve,
            speed_rate=speed_rate,
            left_trim=left_trim,
            right_trim=right_trim,
            clock=clock,
        )
        self._client = client or httpx.AsyncClient(
            base_url=f"http://{host}:{port}",
            timeout=httpx.Timeout(timeout),
        )
        self._owns_client = client is None

    # --- Transport -----------------------------------------------------------

    async def _open(self) -> None:
        return None

    async def _close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, command: dict, *, parse_feedback: bool) -> dict | None:
        """Send one JSON command over HTTP and return the decoded reply."""
        started = time.monotonic()
        try:
            response = await self._client.get(_ENDPOINT, params={"json": json.dumps(command)})
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            self._record_error(exc)
            raise RoverTimeoutError(f"WAVE ROVER did not answer in {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            self._record_error(exc)
            raise RoverConnectionError(f"WAVE ROVER request failed: {exc}") from exc
        except ValueError as exc:
            self._record_error(exc)
            raise RoverProtocolError(f"WAVE ROVER sent invalid JSON: {exc}") from exc

        self._record_ok(started=started)
        if parse_feedback and isinstance(payload, dict):
            self._feedback = parse_chassis_feedback(payload)
        return payload
