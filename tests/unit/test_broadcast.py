"""Tests for the result notifications.

This is the bridge between the camera's thread and the interface's event loop, so
both paths are exercised: the ordinary one and the cross-thread one.
"""

from __future__ import annotations

import asyncio
import threading

from app.ai.broadcast import ResultBroadcaster


async def test_a_subscriber_is_woken_when_a_result_arrives() -> None:
    broadcaster = ResultBroadcaster()
    broadcaster.bind(asyncio.get_running_loop())
    listener = broadcaster.subscribe()

    broadcaster.notify()

    await asyncio.wait_for(listener.wait(), timeout=1)
    assert listener.is_set()


async def test_the_notification_can_come_from_another_thread() -> None:
    """This is how the camera uses it: a plain thread, never the event loop."""
    broadcaster = ResultBroadcaster()
    broadcaster.bind(asyncio.get_running_loop())
    listener = broadcaster.subscribe()

    thread = threading.Thread(target=broadcaster.notify)
    thread.start()
    thread.join()

    await asyncio.wait_for(listener.wait(), timeout=1)


async def test_every_subscriber_is_woken() -> None:
    broadcaster = ResultBroadcaster()
    broadcaster.bind(asyncio.get_running_loop())
    first = broadcaster.subscribe()
    second = broadcaster.subscribe()

    assert broadcaster.listeners == 2
    broadcaster.notify()

    await asyncio.wait_for(first.wait(), timeout=1)
    await asyncio.wait_for(second.wait(), timeout=1)


async def test_unsubscribing_stops_the_notifications() -> None:
    """A closed browser tab must not be kept alive by the broadcaster."""
    broadcaster = ResultBroadcaster()
    broadcaster.bind(asyncio.get_running_loop())
    listener = broadcaster.subscribe()
    broadcaster.unsubscribe(listener)

    broadcaster.notify()
    await asyncio.sleep(0.05)

    assert broadcaster.listeners == 0
    assert listener.is_set() is False


async def test_notifying_without_listeners_is_not_an_error() -> None:
    broadcaster = ResultBroadcaster()
    broadcaster.bind(asyncio.get_running_loop())

    broadcaster.notify()
    await asyncio.sleep(0.05)


async def test_notifying_before_binding_is_dropped_quietly() -> None:
    """At import time there is no loop yet; that must not raise."""
    ResultBroadcaster().notify()


async def test_notifying_after_the_loop_is_gone_does_not_raise() -> None:
    broadcaster = ResultBroadcaster()
    loop = asyncio.new_event_loop()
    broadcaster.bind(loop)
    broadcaster.subscribe()
    loop.close()

    broadcaster.notify()
