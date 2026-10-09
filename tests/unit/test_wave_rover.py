"""Tests for the WAVE ROVER Wi-Fi driver.

The payloads used here are real: they were read from the physical chassis over
HTTP before writing the driver, so the parser is tested against reality rather
than against an invented format.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import DEFAULT_BATTERY_CURVE
from app.rover.models import ChargeState, ConnectionState, MotionCommand
from app.rover.wave_rover_wifi import (
    PROTOCOL_MAX_SPEED,
    WaveRoverWifiDriver,
    battery_percentage,
    mix_differential,
    next_charge_state,
    parse_chassis_feedback,
)

# Captured from the unit: GET /js?json={"T":130}
REAL_FEEDBACK = {
    "T": 1001,
    "L": 0,
    "R": 0,
    "r": -5.157709,
    "p": -18.0168,
    "y": 168.1877,
    "temp": 61.66667,
    "v": 12.15782,
    "c": 582.0001,
    "pwr": 8940.001,
    "ov": False,
}

# Captured from the unit: GET /js?json={"T":126}
REAL_IMU = {
    "T": 1002,
    "r": -5.659261,
    "p": -17.9675,
    "y": 168.4459,
    "ax": 320.9375,
    "ay": -107.8516,
    "az": 984.4629,
    "gx": 2.25625,
    "gy": -0.14375,
    "gz": 0.13125,
    "mx": 32,
    "my": 15,
    "mz": -60,
    "temp": 61.66667,
}


# --- differential mixing ------------------------------------------------------


def test_full_forward_drives_both_wheels_equally() -> None:
    left, right = mix_differential(1.0, 0.0, PROTOCOL_MAX_SPEED)
    assert left == pytest.approx(0.5)
    assert right == pytest.approx(0.5)


def test_spin_in_place_turns_wheels_opposite() -> None:
    left, right = mix_differential(0.0, 1.0, PROTOCOL_MAX_SPEED)
    assert left == pytest.approx(-0.5)
    assert right == pytest.approx(0.5)


def test_forward_left_keeps_the_ratio_within_range() -> None:
    left, right = mix_differential(1.0, 1.0, PROTOCOL_MAX_SPEED)
    # Right is asked for 2.0, so the pair is scaled down to fit +-0.5.
    assert left == pytest.approx(0.0)
    assert right == pytest.approx(0.5)
    assert max(abs(left), abs(right)) <= PROTOCOL_MAX_SPEED


def test_mixing_never_exceeds_the_protocol_range() -> None:
    for linear in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for angular in (-1.0, -0.3, 0.0, 0.3, 1.0):
            left, right = mix_differential(linear, angular, PROTOCOL_MAX_SPEED)
            assert -PROTOCOL_MAX_SPEED <= left <= PROTOCOL_MAX_SPEED
            assert -PROTOCOL_MAX_SPEED <= right <= PROTOCOL_MAX_SPEED


def test_stop_mixes_to_zero() -> None:
    assert mix_differential(0.0, 0.0, PROTOCOL_MAX_SPEED) == (0.0, 0.0)


def test_trim_corrects_a_chassis_that_veers() -> None:
    """If one side runs faster, trim it down so both match."""
    left, right = mix_differential(1.0, 0.0, PROTOCOL_MAX_SPEED, left_trim=0.9, right_trim=1.0)

    assert left == pytest.approx(0.45)
    assert right == pytest.approx(0.5)


def test_trim_never_exceeds_the_protocol_range() -> None:
    left, right = mix_differential(1.0, 0.0, PROTOCOL_MAX_SPEED, left_trim=2.0, right_trim=2.0)

    assert left == pytest.approx(PROTOCOL_MAX_SPEED)
    assert right == pytest.approx(PROTOCOL_MAX_SPEED)


# --- battery ------------------------------------------------------------------


def test_battery_percentage_follows_the_curve_endpoints() -> None:
    assert battery_percentage(12.6, DEFAULT_BATTERY_CURVE) == 100.0
    assert battery_percentage(9.9, DEFAULT_BATTERY_CURVE) == 0.0


def test_battery_percentage_interpolates_between_curve_points() -> None:
    # 11.25 V sits halfway between (11.10, 25) and (11.40, 40).
    assert battery_percentage(11.25, DEFAULT_BATTERY_CURVE) == pytest.approx(32.5, abs=0.1)


def test_battery_percentage_is_clamped_beyond_the_curve() -> None:
    assert battery_percentage(20.0, DEFAULT_BATTERY_CURVE) == 100.0
    assert battery_percentage(1.0, DEFAULT_BATTERY_CURVE) == 0.0


def test_the_curve_does_not_hide_a_dead_pack() -> None:
    """The reason the linear map was unsafe: 10.5 V on a 3S Li-ion is nearly empty.

    A straight 9.9..12.6 line would report 22 % here and an operator could keep
    driving a dead pack.
    """
    assert battery_percentage(10.5, DEFAULT_BATTERY_CURVE) == pytest.approx(5.0)


def test_battery_percentage_is_monotonic_with_voltage() -> None:
    previous = -1.0
    for tenth in range(99, 127):  # 9.9 V .. 12.6 V
        value = battery_percentage(tenth / 10.0, DEFAULT_BATTERY_CURVE)
        assert value >= previous - 1e-9
        previous = value


def test_battery_percentage_handles_an_empty_curve_safely() -> None:
    assert battery_percentage(12.0, []) == 0.0


# --- charger detection (inferred from the voltage trend) -----------------------


def test_next_charge_state_treats_a_steep_rise_as_charging() -> None:
    assert next_charge_state(200.0, ChargeState.UNKNOWN) is ChargeState.CHARGING


def test_next_charge_state_treats_a_steep_fall_as_discharging() -> None:
    assert next_charge_state(-200.0, ChargeState.UNKNOWN) is ChargeState.DISCHARGING


def test_next_charge_state_keeps_its_verdict_while_the_voltage_is_flat() -> None:
    """Hysteresis: the answer must not flicker while the voltage merely wanders."""
    assert next_charge_state(1.0, ChargeState.CHARGING) is ChargeState.CHARGING
    assert next_charge_state(-1.0, ChargeState.DISCHARGING) is ChargeState.DISCHARGING


def test_next_charge_state_ignores_the_slow_idle_drain() -> None:
    """The measured idle drain is ~20 mV/min; the threshold must not catch it."""
    assert next_charge_state(20.0, ChargeState.UNKNOWN) is ChargeState.UNKNOWN
    assert next_charge_state(-20.0, ChargeState.UNKNOWN) is ChargeState.UNKNOWN


async def test_status_flips_between_charging_and_discharging_with_the_trend() -> None:
    """A moving average of voltages, drifting like the real pack does.

    The trend is only judged once the window has real history (60 s), so the test
    advances an injectable clock instead of sleeping, and the rise has to age out
    of the 120 s window before the fall is visible - exactly like production.
    """

    class FakeClock:
        def __init__(self) -> None:
            self._now = 1000.0

        def __call__(self) -> float:
            self._now += 1.0
            return self._now

    readings = {"v": 12.05}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = dict(REAL_FEEDBACK)
        payload["v"] = readings["v"]
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    rover = WaveRoverWifiDriver(host="rover", client=client, clock=FakeClock())  # type: ignore[arg-type]
    await rover.connect()

    # A steady baseline before anything can be judged (the window needs 60 s).
    for _ in range(80):
        await rover.status()
    assert (await rover.status()).battery_charge_state is ChargeState.UNKNOWN

    # Rising toward 12.6: a charger would push the voltage up.
    for step in range(40):
        readings["v"] = 12.05 + step * 0.01
        await rover.status()
    assert (await rover.status()).battery_charge_state is ChargeState.CHARGING

    # Held flat: the verdict stays (a charger at float voltage, not a flicker).
    for _ in range(20):
        await rover.status()
    assert (await rover.status()).battery_charge_state is ChargeState.CHARGING

    # Falling back down: the charger is gone. The rise ages out of the 120 s
    # window first, then the fall dominates and the latch flips.
    for step in range(40):
        readings["v"] = 12.05 + (39 - step) * 0.01
        await rover.status()
    for _ in range(220):
        readings["v"] = 12.05
        await rover.status()
    assert (await rover.status()).battery_charge_state is ChargeState.DISCHARGING


# --- feedback parsing ---------------------------------------------------------


def test_parses_the_real_chassis_feedback() -> None:
    feedback = parse_chassis_feedback(REAL_FEEDBACK)

    assert feedback.voltage_v == pytest.approx(12.15782)
    assert feedback.temperature_c == pytest.approx(61.66667)
    assert feedback.yaw == pytest.approx(168.1877)
    assert feedback.overvoltage is False


def test_rejects_a_payload_that_is_not_base_feedback() -> None:
    from app.core.exceptions import RoverProtocolError

    with pytest.raises(RoverProtocolError):
        parse_chassis_feedback(REAL_IMU)


# --- speed rate (boot.mission sets it to 0) -----------------------------------


def build_rate_driver(rate_reply: dict, sent: list[dict]) -> WaveRoverWifiDriver:
    def handler(request: httpx.Request) -> httpx.Response:
        command = json.loads(request.url.params["json"])
        sent.append(command)
        if command.get("T") == 139:
            return httpx.Response(200, json=rate_reply)
        return httpx.Response(200, json=REAL_FEEDBACK)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    return WaveRoverWifiDriver(host="rover", client=client)


async def test_connect_sets_the_speed_rate_when_the_chassis_has_it_at_zero() -> None:
    """With a rate of 0 the chassis ignores every motion command."""
    sent: list[dict] = []
    rover = build_rate_driver({"T": 139, "L": 0, "R": 0}, sent)

    await rover.connect()

    assert {"T": 138, "L": 1.0, "R": 1.0} in sent


async def test_connect_respects_a_speed_rate_set_by_hand() -> None:
    sent: list[dict] = []
    rover = build_rate_driver({"T": 139, "L": 1, "R": 1}, sent)

    await rover.connect()

    assert not any(command.get("T") == 138 for command in sent)


# --- driver over a mocked HTTP transport --------------------------------------


def build_driver(
    sent: list[dict], reply: dict = REAL_FEEDBACK, **kwargs: object
) -> WaveRoverWifiDriver:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.url.params["json"]))
        return httpx.Response(200, json=reply)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    return WaveRoverWifiDriver(host="rover", client=client, **kwargs)  # type: ignore[arg-type]


async def test_connect_queries_the_chassis_and_reports_connected() -> None:
    sent: list[dict] = []
    rover = build_driver(sent)

    await rover.connect()

    assert rover.is_connected is True
    assert sent[0] == {"T": 130}


async def test_move_sends_left_and_right_wheel_speeds() -> None:
    sent: list[dict] = []
    rover = build_driver(sent)
    await rover.connect()

    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    assert sent[-1] == {"T": 1, "L": 0.5, "R": 0.5}


async def test_stop_sends_zero_speeds() -> None:
    sent: list[dict] = []
    rover = build_driver(sent)
    await rover.connect()
    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    await rover.stop()

    assert sent[-1] == {"T": 1, "L": 0.0, "R": 0.0}
    status = await rover.status()
    assert status.moving is False


async def test_move_applies_the_wheel_trim() -> None:
    """Calibration: the faster side is trimmed so the chassis runs straight."""
    sent: list[dict] = []
    rover = build_driver(sent, left_trim=0.8, right_trim=1.0)
    await rover.connect()

    await rover.move(MotionCommand(linear=1.0, angular=0.0))

    assert sent[-1] == {"T": 1, "L": 0.4, "R": 0.5}


async def test_move_without_connection_is_refused() -> None:
    from app.core.exceptions import RoverConnectionError

    rover = build_driver([])

    with pytest.raises(RoverConnectionError):
        await rover.move(MotionCommand(linear=1.0, angular=0.0))


async def test_status_exposes_voltage_and_battery_percentage() -> None:
    rover = build_driver([])
    await rover.connect()

    status = await rover.status()

    assert status.connection is ConnectionState.CONNECTED
    # The voltage is the rolling mean, rounded to the millivolt.
    assert status.battery_voltage == pytest.approx(12.158, abs=0.001)
    assert status.battery_percentage is not None
    assert 80 < status.battery_percentage <= 100
    assert status.battery_current_ma == pytest.approx(582.0, abs=0.1)
    assert status.latency_ms is not None


async def test_status_smooths_the_voltage_so_the_percentage_does_not_jump() -> None:
    """One spiky reading must not bounce the charge level around the plateau."""
    reading = {"v": 12.1}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = dict(REAL_FEEDBACK)
        payload["v"] = reading["v"]
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    rover = WaveRoverWifiDriver(host="rover", client=client)

    await rover.connect()
    for _ in range(8):
        await rover.status()

    # A 0.6 V dip alone would read ~45 % on the curve; the rolling mean holds.
    reading["v"] = 11.5
    for _ in range(5):
        last = await rover.status()

    assert last.battery_voltage > 11.5
    assert last.battery_percentage > 50.0


async def test_a_hanging_rover_raises_a_timeout() -> None:
    from app.core.exceptions import RoverTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no answer", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    rover = WaveRoverWifiDriver(host="rover", client=client)

    with pytest.raises(RoverTimeoutError):
        await rover.connect()


async def test_an_http_error_does_not_wedge_the_driver() -> None:
    """A failure must be reported, but a later success must recover control."""
    from app.core.exceptions import RoverConnectionError

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=REAL_FEEDBACK)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rover")
    rover = WaveRoverWifiDriver(host="rover", client=client)

    with pytest.raises(RoverConnectionError):
        await rover.connect()

    # The chassis is still there: the very next command must work.
    status = await rover.status()
    assert status.connection is ConnectionState.CONNECTED
    assert rover.is_connected is True
