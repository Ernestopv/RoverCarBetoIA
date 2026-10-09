"""Tests for the camera layer.

Nothing here touches real hardware or FFmpeg: the process is replaced by a tiny
Python command so the lifecycle and the supervisor can be tested deterministically.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.camera.factory import create_camera
from app.camera.imx500 import Imx500Camera
from app.camera.simulator import SimulatedCamera, consecutive_failures, next_backoff
from app.camera.stream import normalize_path, publish_url, whep_path
from app.core.config import Settings
from app.core.exceptions import CameraStreamError

# A stand-in "publisher" that just sleeps, and one that exits immediately.
SLEEPING = [sys.executable, "-c", "import time; time.sleep(30)"]
DYING = [sys.executable, "-c", "raise SystemExit(3)"]


class StubCamera(SimulatedCamera):
    """SimulatedCamera whose FFmpeg command is replaced by `argv`."""

    def __init__(self, argv: list[str], **kwargs: object) -> None:
        super().__init__(
            rtsp_url="rtsp://localhost:8554/rover",
            stream_path="rover",
            webrtc_port=8889,
            **kwargs,  # type: ignore[arg-type]
        )
        self._argv = argv

    def command(self) -> list[str]:
        return self._argv


# --- stream URL helpers ------------------------------------------------------


def test_normalize_path_strips_slashes() -> None:
    assert normalize_path("/rover/") == "rover"
    assert normalize_path("rover") == "rover"


def test_publish_url_points_at_mediamtx() -> None:
    assert publish_url("mediamtx", 8554, "/rover/") == "rtsp://mediamtx:8554/rover"


def test_whep_path_is_what_the_browser_appends() -> None:
    assert whep_path("rover") == "/rover/whep"


# --- factory -----------------------------------------------------------------


def test_factory_builds_the_simulator() -> None:
    settings = Settings(_env_file=None, camera_mode="simulator")
    assert isinstance(create_camera(settings), SimulatedCamera)


def test_factory_builds_the_imx500_driver() -> None:
    settings = Settings(_env_file=None, camera_mode="imx500")
    camera = create_camera(settings)
    assert isinstance(camera, Imx500Camera)


# --- ffmpeg command -----------------------------------------------------------


def test_ffmpeg_command_publishes_to_mediamtx_without_writing_files() -> None:
    camera = SimulatedCamera(
        rtsp_url="rtsp://mediamtx:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
        width=640,
        height=480,
        fps=15,
        bitrate_kbps=1200,
    )

    command = camera.command()

    assert command[0] == "ffmpeg"
    assert "lavfi" in command
    assert "testsrc2=size=640x480:rate=15" in command
    assert command[-1] == "rtsp://mediamtx:8554/rover"
    assert "-tune" in command and "zerolatency" in command
    # Nothing may be written to disk: the RTSP muxer is the only output.
    assert "-y" not in command
    assert not any(arg.endswith(".mp4") or arg.endswith(".mkv") for arg in command)


async def test_status_reports_configuration_before_start() -> None:
    camera = SimulatedCamera(
        rtsp_url="rtsp://localhost:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
        width=800,
        height=600,
        fps=20,
    )

    status = await camera.status()

    assert status.mode == "simulator"
    assert status.running is False
    assert status.width == 800
    assert status.height == 600
    assert status.stream_path == "rover"
    assert status.webrtc_port == 8889
    assert status.last_error is None


# --- IMX500 driver -------------------------------------------------------------


async def test_imx500_status_reports_the_network_before_start() -> None:
    camera = Imx500Camera(
        network_file="/usr/share/imx500-models/imx500_network_efficientdet_lite0_pp.rpk",
        rtsp_url="rtsp://mediamtx:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
    )

    status = await camera.status()

    assert status.mode == "imx500"
    assert status.running is False
    assert status.model == "imx500_network_efficientdet_lite0_pp.rpk"
    assert status.last_error is None


def test_imx500_publishes_over_rtsp_and_never_to_a_file() -> None:
    camera = Imx500Camera(
        network_file="model.rpk",
        rtsp_url="rtsp://mediamtx:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
    )

    target = camera.ffmpeg_target()

    assert target.endswith("rtsp://mediamtx:8554/rover")
    assert "-f rtsp" in target
    assert not any(target.endswith(suffix) for suffix in (".mp4", ".h264", ".mkv"))


async def test_imx500_fails_with_an_actionable_message_off_the_pi() -> None:
    """On any machine without picamera2 the failure must be explicit."""
    camera = Imx500Camera(
        network_file="model.rpk",
        rtsp_url="rtsp://localhost:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
    )

    with pytest.raises(CameraStreamError) as excinfo:
        await camera.start()

    message = str(excinfo.value)
    assert "picamera2" in message
    assert camera.is_running is False
    # The reason is kept so /camera/status can explain it.
    assert (await camera.status()).last_error is not None


def test_imx500_mirrors_only_when_the_mount_needs_it() -> None:
    def build(**kwargs: object) -> Imx500Camera:
        return Imx500Camera(
            network_file="model.rpk",
            rtsp_url="rtsp://mediamtx:8554/rover",
            stream_path="rover",
            webrtc_port=8889,
            **kwargs,  # type: ignore[arg-type]
        )

    assert build().transform_args() == {"hflip": 0, "vflip": 0}
    # 180 degrees on the robot = both axes mirrored.
    assert build(hflip=True, vflip=True).transform_args() == {"hflip": 1, "vflip": 1}


def test_factory_forwards_the_mirror_settings() -> None:
    settings = Settings(
        _env_file=None,
        camera_mode="imx500",
        camera_hflip=True,
        camera_vflip=True,
    )

    camera = create_camera(settings)

    assert isinstance(camera, Imx500Camera)
    assert camera.transform_args() == {"hflip": 1, "vflip": 1}


# --- restart backoff policy ---------------------------------------------------


def test_backoff_escalates_with_consecutive_failures() -> None:
    delays = (1.0, 2.0, 5.0)

    assert next_backoff(0, delays) == 1.0
    assert next_backoff(1, delays) == 2.0
    assert next_backoff(2, delays) == 5.0
    # Clamped at the last delay: never grows without bound.
    assert next_backoff(99, delays) == 5.0
    assert next_backoff(0, ()) == 0.0


def test_a_healthy_run_resets_the_backoff() -> None:
    # A publisher that stayed up long enough starts over at the first delay,
    # instead of inheriting failures from hours earlier.
    assert consecutive_failures(previous=4, uptime_s=120.0, healthy_uptime_s=10.0) == 0
    assert consecutive_failures(previous=0, uptime_s=10.0, healthy_uptime_s=10.0) == 0


def test_a_quick_crash_escalates_the_backoff() -> None:
    assert consecutive_failures(previous=0, uptime_s=0.5, healthy_uptime_s=10.0) == 1
    assert consecutive_failures(previous=1, uptime_s=0.5, healthy_uptime_s=10.0) == 2


# --- lifecycle ----------------------------------------------------------------


async def test_start_and_stop_manage_the_process() -> None:
    camera = StubCamera(SLEEPING)

    await camera.start()
    try:
        assert camera.is_running is True
        assert (await camera.status()).running is True
    finally:
        await camera.stop()

    assert camera.is_running is False


async def test_start_is_idempotent() -> None:
    camera = StubCamera(SLEEPING)

    await camera.start()
    await camera.start()  # must not spawn a second publisher
    try:
        assert camera.is_running is True
    finally:
        await camera.stop()


async def test_missing_ffmpeg_raises_a_camera_error() -> None:
    camera = SimulatedCamera(
        rtsp_url="rtsp://localhost:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
        ffmpeg="ffmpeg-does-not-exist-xyz",
    )

    with pytest.raises(CameraStreamError):
        await camera.start()


async def test_supervisor_restarts_a_crashed_publisher() -> None:
    camera = StubCamera(DYING, restart_delays=(0.01,))

    await camera.start()
    try:
        # Give the supervisor time to notice the exit and respawn.
        await asyncio.sleep(0.2)
        status = await camera.status()
        assert status.restarts >= 1
        assert status.last_error is not None
    finally:
        await camera.stop()


async def test_stop_without_start_is_safe() -> None:
    camera = StubCamera(SLEEPING)
    await camera.stop()
    assert camera.is_running is False
