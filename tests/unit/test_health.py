"""Tests for the stream health watchdog.

The supervision loop accepts injected probe/restart callables, so it is tested
with fake signals; the RTSP probe is tested against a tiny TCP server serving a
canned reply. No camera, no MediaMTX involved.
"""

from __future__ import annotations

import asyncio
import socket
import threading

import pytest

from app.camera.health import rtsp_describe_ok, supervise_stream, wait_until_published

# --- the RTSP probe -----------------------------------------------------------


def serve_once(reply: bytes) -> tuple[int, threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def handler() -> None:
        conn, _ = listener.accept()
        try:
            conn.recv(4096)
            conn.sendall(reply)
        finally:
            conn.close()
            listener.close()

    thread = threading.Thread(target=handler, daemon=True)
    thread.start()
    return port, thread


def test_a_live_publish_answers_describe_with_200() -> None:
    port, thread = serve_once(b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n")

    assert rtsp_describe_ok(f"rtsp://127.0.0.1:{port}/rover") is True
    thread.join(timeout=2)


def test_anything_but_200_is_a_dead_publish() -> None:
    port, thread = serve_once(b"RTSP/1.0 404 Not Found\r\n\r\n")

    assert rtsp_describe_ok(f"rtsp://127.0.0.1:{port}/rover") is False
    thread.join(timeout=2)


def test_unreachable_media_mtx_is_a_dead_publish() -> None:
    # Port 1 is essentially never open; the probe must not raise.
    assert rtsp_describe_ok("rtsp://127.0.0.1:1/rover", timeout=0.5) is False


def test_a_non_rtsp_url_is_not_live() -> None:
    assert rtsp_describe_ok("http://example.com/rover") is False


# --- the supervision loop -----------------------------------------------------


async def run_watchdog(**overrides) -> tuple[asyncio.Task[None], list[str]]:
    restarts: list[str] = []
    overrides.setdefault("probe", lambda: True)
    overrides.setdefault("restart", lambda: _record(restarts))
    overrides.setdefault("poll_seconds", 0.01)
    overrides.setdefault("restart_delays", (0.01,))
    task = asyncio.create_task(supervise_stream(**overrides))
    return task, restarts


async def _record(restarts: list[str]) -> None:
    restarts.append("restart")


async def test_a_healthy_stream_never_restarts_the_camera() -> None:
    task, restarts = await run_watchdog()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert restarts == []


async def test_a_dead_stream_restarts_the_camera() -> None:
    task, restarts = await run_watchdog(probe=lambda: False, fail_before_restart=1)
    await asyncio.sleep(0.08)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(restarts) >= 2


async def test_an_inactive_camera_is_never_restarted() -> None:
    """While deliberately stopped (e.g. a model reload) nothing is restarted."""
    task, restarts = await run_watchdog(
        probe=lambda: False,
        active=lambda: False,
        fail_before_restart=1,
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert restarts == []


async def test_a_healthy_probe_resets_the_restart_loop() -> None:
    alive = {"value": False}
    task, restarts = await run_watchdog(
        probe=lambda: alive["value"],
        fail_before_restart=1,
    )

    await asyncio.sleep(0.03)  # dead: restarts
    alive["value"] = True
    await asyncio.sleep(0.03)  # healthy: the backoff resets
    restarts_before = len(restarts)
    alive["value"] = False
    await asyncio.sleep(0.03)  # dead again: restarts again

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert restarts_before >= 1
    assert len(restarts) > restarts_before


async def test_a_failed_restart_does_not_stop_the_watchdog() -> None:
    async def failing_restart() -> None:
        raise RuntimeError("camera is wedged")

    task = asyncio.create_task(
        supervise_stream(
            probe=lambda: False,
            restart=failing_restart,
            poll_seconds=0.01,
            fail_before_restart=1,
            restart_delays=(0.01,),
        )
    )
    await asyncio.sleep(0.05)  # must not raise or die
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- waiting for the publish after a model switch ------------------------------


async def test_wait_until_published_returns_when_the_publish_comes_back() -> None:
    alive = {"value": False}

    async def become_live() -> None:
        await asyncio.sleep(0.02)
        alive["value"] = True

    flipper = asyncio.create_task(become_live())

    assert (
        await wait_until_published(lambda: alive["value"], max_seconds=2.0, interval=0.01) is True
    )
    await flipper


async def test_wait_until_published_gives_up_after_the_timeout() -> None:
    assert await wait_until_published(lambda: False, max_seconds=0.05, interval=0.01) is False
