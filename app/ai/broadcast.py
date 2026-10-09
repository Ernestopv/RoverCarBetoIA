"""Notifications when the sensor has produced a new inference result.

The camera works in its own thread, and the interface wants to know *when* there is
something new rather than asking repeatedly. This is the bridge between those two
worlds.

Subscribers are only **woken up**, they are not handed the data: each one then reads
the snapshot it cares about. That keeps a slow browser from holding up the
inference or the other listeners, and it keeps the camera from knowing anything
about WebSockets.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class ResultBroadcaster:
    """Wakes subscribers up when there is a fresh result to read."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listeners: set[asyncio.Event] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the loop notifications have to be delivered on.

        Called once, from the application's startup, because the camera's thread
        cannot touch asyncio objects directly.
        """
        self._loop = loop

    @property
    def listeners(self) -> int:
        """How many subscribers are waiting. Useful in logs and tests."""
        return len(self._listeners)

    def subscribe(self) -> asyncio.Event:
        event = asyncio.Event()
        self._listeners.add(event)
        return event

    def unsubscribe(self, event: asyncio.Event) -> None:
        self._listeners.discard(event)

    def notify(self) -> None:
        """Announce a new result. Safe to call from any thread, and never blocks.

        Called by the camera's inference loop, which must not wait for the network.
        """
        loop = self._loop
        if loop is None or not self._listeners or loop.is_closed():
            return

        try:
            loop.call_soon_threadsafe(self._wake)
        except RuntimeError:
            # The loop shut down between the check above and this call.
            logger.debug("Could not notify subscribers: the event loop is gone")

    def _wake(self) -> None:
        """Runs on the event loop, never on the caller's thread."""
        for listener in self._listeners:
            listener.set()
