"""Tests for the WAVE ROVER serial (UART) transport.

The wire is exercised through a fake serial port, so no real hardware and no
motion: the serial driver must obey the same contract as the Wi-Fi one, which the
shared base already guarantees. The payloads match the chassis JSON protocol.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.core.exceptions import RoverTimeoutError
from app.rover.factory import create_rover
from app.rover.wave_rover_serial import SERIAL_BAUD, WaveRoverSerialDriver


class FakeSerial:
    """Minimal stand-in for a pyserial handle."""

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self._queue = list(replies or [])
        self.written: list[bytes] = []
        self.readline_calls = 0

    def reset_input_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        self.readline_calls += 1
        return self._queue.pop(0) if self._queue else b""


def driver_with(*replies: dict) -> tuple[WaveRoverSerialDriver, FakeSerial]:
    handle = FakeSerial([(json.dumps(reply) + "\n").encode("utf-8") for reply in replies])
    driver = WaveRoverSerialDriver(timeout=0.1)
    driver._ser = handle  # inject the fake port without opening a real one
    return driver, handle


FEEDBACK = {
    "T": 1001,
    "L": 0,
    "R": 0,
    "r": 1.2,
    "p": -3.4,
    "y": 155.5,
    "temp": 60.0,
    "v": 12.15782,
    "c": 582.0001,
    "ov": False,
}


def test_motion_command_is_written_as_json_line() -> None:
    driver, handle = driver_with()

    reply = driver._request_blocking({"T": 1, "L": 0.1, "R": 0.2}, parse_feedback=False)

    assert reply is None
    assert handle.written == [b'{"T": 1, "L": 0.1, "R": 0.2}\n']
    assert driver.is_connected  # the state is healthy even without a reply


def test_motion_command_does_not_wait_for_a_reply() -> None:
    """Motion must return as soon as the command is sent, like Wi-Fi does."""
    driver, handle = driver_with({"T": 1001})

    reply = driver._request_blocking({"T": 1, "L": 0.0, "R": 0.0}, parse_feedback=False)

    assert reply is None
    assert handle.readline_calls == 0  # never read: no waiting for the next line


def test_feedback_reply_is_parsed_into_chassis_feedback() -> None:
    driver, handle = driver_with(FEEDBACK)

    reply = driver._request_blocking({"T": 130}, parse_feedback=True)

    assert reply is not None
    assert reply["T"] == 1001
    assert driver._feedback is not None
    assert driver._feedback.voltage_v == pytest.approx(12.15782)
    assert driver._feedback.yaw == pytest.approx(155.5)


def test_feedback_without_a_reply_times_out() -> None:
    driver, _ = driver_with()
    driver._timeout = 0.05

    with pytest.raises(RoverTimeoutError):
        driver._request_blocking({"T": 130}, parse_feedback=False)


def test_ignores_non_json_noise_before_the_reply() -> None:
    driver, handle = driver_with()
    handle._queue = [b"boot log line\n", (json.dumps(FEEDBACK) + "\n").encode("utf-8")]

    reply = driver._request_blocking({"T": 130}, parse_feedback=True)

    assert reply is not None
    assert reply["T"] == 1001


def test_skips_the_echo_of_our_own_command() -> None:
    # The chassis mirrors the received command back before answering; that echo
    # must never be mistaken for the real reply.
    command = {"T": 130}
    driver, handle = driver_with()
    handle._queue = [
        (json.dumps(command) + "\n").encode("utf-8"),
        (json.dumps(FEEDBACK) + "\n").encode("utf-8"),
    ]

    reply = driver._request_blocking(command, parse_feedback=True)

    assert reply == FEEDBACK
    assert driver._feedback is not None
    assert driver._feedback.yaw == pytest.approx(155.5)


def test_factory_builds_the_serial_driver_from_config() -> None:
    settings = Settings(
        _env_file=None,
        rover_mode="hardware",
        wave_rover_transport="serial",
        wave_rover_serial_port="/dev/ttyAMA0",
        wave_rover_host="192.168.4.1",
        wave_rover_port=80,
    )

    rover = create_rover(settings)

    assert isinstance(rover, WaveRoverSerialDriver)
    assert rover._port == "/dev/ttyAMA0"


def test_default_transport_is_wifi() -> None:
    from app.rover.wave_rover_wifi import WaveRoverWifiDriver

    settings = Settings(
        _env_file=None,
        rover_mode="hardware",
        wave_rover_host="192.168.4.1",
        wave_rover_port=80,
    )

    assert isinstance(create_rover(settings), WaveRoverWifiDriver)


def test_serial_constants_match_the_protocol() -> None:
    assert SERIAL_BAUD == 115200
