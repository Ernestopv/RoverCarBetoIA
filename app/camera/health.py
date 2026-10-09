"""Health of the live RTSP publish, and recovery when it dies.

The camera publishes to MediaMTX over RTSP. Restarting MediaMTX drops that
connection, and the camera's FFmpeg does not reconnect on its own (T-003): the
publish stays dead until the camera restarts.

MediaMTX's own HTTP API was not usable for this (it answered 404 to every path
without any hint), so the probe here is a plain RTSP ``DESCRIBE`` on the very
URL the camera publishes to — exactly what a client would experience: ``200 OK``
means the path is really being served live, anything else means it is not. No
dependencies, no credentials.

Everything is injectable so the supervision loop is testable without RTSP or a
camera.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: How often the publish is probed.
POLL_SECONDS = 2.0
#: Consecutive dead probes before the camera is restarted.
FAIL_BEFORE_RESTART = 3
#: Wait between restarts, bounded so a still-dead MediaMTX is not hammered.
RESTART_DELAYS = (5.0, 15.0, 30.0)
#: Timeout for each RTSP probe.
PROBE_TIMEOUT = 2.0
#: How long a model switch waits for the publish to come back before giving up.
PUBLISH_READY_TIMEOUT = 30.0


def rtsp_describe_ok(url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """True when MediaMTX answers ``DESCRIBE`` for this URL with ``200 OK``.

    ``url`` is the publish URL, e.g. ``rtsp://mediamtx:8554/rover``.
    """
    parts = urlsplit(url)
    if parts.scheme != "rtsp" or not parts.hostname:
        return False

    port = parts.port or 554
    path = parts.path.lstrip("/") or "stream"
    try:
        with socket.create_connection((parts.hostname, port), timeout=timeout) as sock:
            request = (
                f"DESCRIBE rtsp://{parts.hostname}:{port}/{path} RTSP/1.0\r\nCSeq: 1\r\n\r\n"
            ).encode()
            sock.sendall(request)
            reply = sock.recv(4096)
    except OSError:
        # MediaMTX unreachable: that is not a healthy publish.
        return False

    status = reply.split(b"\r\n", 1)[0].decode(errors="replace")
    return status.startswith("RTSP/1.0 200")


async def wait_until_published(
    probe: Callable[[], bool],
    max_seconds: float = PUBLISH_READY_TIMEOUT,
    interval: float = PROBE_TIMEOUT,
) -> bool:
    """Wait for the publish to be live again, up to ``max_seconds`` seconds.

    Used by the model switch: the camera restarts in under a second, but the
    sensor takes several more seconds to produce frames and republish. The
    interface's "loading" window lasts exactly as long as the switch request, so
    the switch answers only once the stream is actually back.
    """
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        if await asyncio.to_thread(probe):
            return True
        await asyncio.sleep(interval)
    return False


async def supervise_stream(
    *,
    probe: Callable[[], bool],
    restart: Callable[[], Awaitable[None]],
    active: Callable[[], bool] = lambda: True,
    poll_seconds: float = POLL_SECONDS,
    fail_before_restart: int = FAIL_BEFORE_RESTART,
    restart_delays: tuple[float, ...] = RESTART_DELAYS,
) -> None:
    """Restart the publisher when the stream is confirmed dead.

    ``probe`` answers "is the stream being served live?" (e.g. a wrapped
    :func:`rtsp_describe_ok`). ``restart`` restarts the publisher. ``active`` says
    whether a restart is allowed right now — while the camera is deliberately
    stopped (e.g. a model reload) nothing should be restarted.

    Runs until cancelled. The first restart waits for ``restart_delays[0]``
    before probing again, escalating with failures and resetting on the first
    healthy probe, so a still-dead MediaMTX is not hammered into a crash loop.
    """
    consecutive = 0
    restart_level = 0

    while True:
        await asyncio.sleep(poll_seconds)
        if not active():
            consecutive = 0
            restart_level = 0
            continue

        live = await asyncio.to_thread(probe)
        if live:
            consecutive = 0
            restart_level = 0
            continue

        consecutive += 1
        if consecutive < fail_before_restart:
            continue

        logger.warning(
            "The live stream has been dead for %d checks; restarting the camera",
            consecutive,
        )
        try:
            await restart()
        except Exception:
            logger.exception("Camera restart after stream loss failed")
        consecutive = 0

        delay = restart_delays[min(restart_level, len(restart_delays) - 1)]
        restart_level = min(restart_level + 1, len(restart_delays) - 1)
        await asyncio.sleep(delay)
