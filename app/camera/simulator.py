"""Simulated camera.

Publishes a synthetic test signal to MediaMTX, so the whole live-video pipeline
(camera -> MediaMTX -> WebRTC -> browser) can be developed and tested without
the Raspberry Pi AI Camera.

**No frame is ever written to disk**: FFmpeg reads a generated source and writes
the encoded stream straight to the RTSP socket. That is what makes the real
IMX500 implementation a drop-in replacement later.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from app.camera.interface import Camera, CameraStatus
from app.core.exceptions import CameraStreamError

logger = logging.getLogger(__name__)

# Backoff between restart attempts, in seconds. Bounded on purpose: a camera
# that keeps dying must not turn into a busy loop.
_RESTART_DELAYS = (1.0, 2.0, 5.0, 10.0)
# A publisher that stayed up this long is a fresh failure, not a crash loop, so
# the backoff starts over instead of escalating forever.
_HEALTHY_UPTIME_S = 10.0
# Number of FFmpeg stderr lines kept for diagnostics.
_STDERR_TAIL = 5


def next_backoff(failures: int, delays: tuple[float, ...]) -> float:
    """Delay before the next attempt, given the consecutive failures so far."""
    if not delays:
        return 0.0
    return delays[min(max(failures, 0), len(delays) - 1)]


def consecutive_failures(previous: int, uptime_s: float, healthy_uptime_s: float) -> int:
    """Update the consecutive-failure counter for a publisher that just died.

    Once the stream has been healthy, the next crash is a new event: without
    this reset, a long-running camera that blips once would wait ten seconds
    because of failures that happened hours earlier.
    """
    if uptime_s >= healthy_uptime_s:
        return 0
    return previous + 1


class SimulatedCamera(Camera):
    """In-memory video source backed by FFmpeg's synthetic signal generator."""

    def __init__(
        self,
        *,
        rtsp_url: str,
        stream_path: str,
        webrtc_port: int,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        bitrate_kbps: int = 2500,
        ffmpeg: str = "ffmpeg",
        mode: str = "simulator",
        restart_delays: tuple[float, ...] = _RESTART_DELAYS,
    ) -> None:
        self._rtsp_url = rtsp_url
        self._stream_path = stream_path
        self._webrtc_port = webrtc_port
        self._width = width
        self._height = height
        self._fps = fps
        self._bitrate_kbps = bitrate_kbps
        self._ffmpeg = ffmpeg
        self._mode = mode
        self._restart_delays = restart_delays or _RESTART_DELAYS

        self._process: asyncio.subprocess.Process | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closing = False
        self._restarts = 0
        self._failures = 0
        self._started_at = 0.0
        self._last_error: str | None = None
        self._stderr_tail: list[str] = []

    # --- Camera contract -----------------------------------------------------

    @property
    def is_running(self) -> bool:
        process = self._process
        return process is not None and process.returncode is None

    async def start(self) -> None:
        if self._monitor is not None:
            return

        self._closing = False
        try:
            await self._spawn()
        except OSError as exc:
            self._last_error = str(exc)
            raise CameraStreamError(f"Could not start the camera publisher: {exc}") from exc

        self._monitor = asyncio.create_task(self._supervise(), name="camera-supervisor")

    async def stop(self) -> None:
        self._closing = True

        monitor, self._monitor = self._monitor, None
        if monitor is not None:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor

        await self._terminate()

    async def status(self) -> CameraStatus:
        return CameraStatus(
            mode=self._mode,
            running=self.is_running,
            width=self._width,
            height=self._height,
            fps=self._fps,
            stream_path=self._stream_path,
            webrtc_port=self._webrtc_port,
            restarts=self._restarts,
            last_error=self._last_error,
        )

    # --- Internals -----------------------------------------------------------

    def command(self) -> list[str]:
        """The FFmpeg command that generates and publishes the test signal."""
        source = f"testsrc2=size={self._width}x{self._height}:rate={self._fps}"
        # fmt: off  -- an argument list reads better as flag/value pairs
        return [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",  # generate in real time instead of as fast as possible
            "-f",
            "lavfi",
            "-i",
            source,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",  # latency is what matters when driving
            "-profile:v",
            "baseline",  # widest browser support
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(self._fps),  # one keyframe per second: fast joins
            "-b:v",
            f"{self._bitrate_kbps}k",
            "-an",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            self._rtsp_url,
        ]
        # fmt: on

    async def _spawn(self) -> None:
        logger.info("Starting simulated camera, publishing to %s", self._rtsp_url)
        process = await asyncio.create_subprocess_exec(
            *self.command(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._process = process
        self._started_at = time.monotonic()
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._drain_stderr(process), name="camera-stderr")

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        """Drain stderr so the pipe never fills up and block FFmpeg."""
        stream = process.stderr
        if stream is None:
            return
        with suppress(asyncio.CancelledError):
            async for raw in stream:
                line = raw.decode(errors="replace").strip()
                if line:
                    self._stderr_tail.append(line)
                    del self._stderr_tail[:-_STDERR_TAIL]

    async def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Camera publisher did not stop in time, killing it")
                process.kill()
                await process.wait()

        stderr_task, self._stderr_task = self._stderr_task, None
        if stderr_task is not None:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task

    async def _supervise(self) -> None:
        """Restart the publisher if it dies unexpectedly, with a bounded backoff."""
        while not self._closing:
            process = self._process
            if process is None:
                return

            code = await process.wait()
            uptime = time.monotonic() - self._started_at
            if self._closing:
                return

            self._restarts += 1
            detail = self._stderr_tail[-1] if self._stderr_tail else "no details"
            self._last_error = f"camera publisher exited with code {code}: {detail}"
            logger.warning("%s (after %.1fs)", self._last_error, uptime)

            # Backoff is driven by consecutive failures, not by the lifetime
            # restart count, so a healthy camera recovers in one second.
            delay = next_backoff(self._failures, self._restart_delays)
            self._failures = consecutive_failures(self._failures, uptime, _HEALTHY_UPTIME_S)
            await asyncio.sleep(delay)
            if self._closing:
                return

            try:
                await self._spawn()
            except OSError as exc:
                self._last_error = f"could not restart the camera: {exc}"
                logger.exception("Could not restart the simulated camera")
                return
