"""Person following (Phase 7).

The first "intelligent behaviour": when an operator enables it, the rover chases a
detected **person** — turning to keep them centred and advancing until they are
close — by issuing motion commands. It is the decision layer of the pipeline in
``AGENTS.md`` §11:

    Perception -> Decision -> Safety validation -> Motion

Design rules (deliberately conservative):

- **Off by default.** No autonomous motion happens until an operator enables it.
- Every command goes through :class:`~app.rover.service.RoverService`, so the
  safety layer clamps it and the watchdog stays armed. This module never talks to
  a motor or a driver directly.
- **The rover never reverses.** It holds a minimum distance (the person's apparent
  size) and, once there, stops: it must not run into the person or back blindly
  into whatever is behind it.
- **Loss of target stops the rover** and, after a grace period, disables following.
- The geometry is pure and dependency-free, so it is testable without hardware.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.ai.detection import Detection, DetectionSnapshot
from app.rover.models import MotionCommand
from app.rover.service import RoverService

logger = logging.getLogger(__name__)

#: Default label to follow. It is a COCO class name from the detector.
DEFAULT_TARGET_LABEL = "person"


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


@dataclass(frozen=True)
class FollowTuning:
    """Tunable parameters of the follow behaviour.

    The values are still bounded by the safety layer; these are the behaviour's
    own, gentler limits.
    """

    target_label: str = DEFAULT_TARGET_LABEL
    min_confidence: float = 0.5
    #: Approach until the person's bbox reaches this height (0..1). It is the
    #: minimum distance: 0.7 means "quite close", 0.5 means "arm's length".
    target_height: float = 0.7
    max_linear: float = 0.4
    max_angular: float = 0.6
    #: Smallest forward speed, so static friction does not stall the approach.
    min_linear: float = 0.15
    #: Dead zone around the target centre and the target height.
    deadband: float = 0.06
    #: Only drive forward when the person is within this distance of the centre;
    #: otherwise turn in place (never drive diagonally toward an obstacle).
    face_deadband: float = 0.2
    #: Seconds without a target before following disables itself.
    lost_timeout: float = 10.0


class FollowStatus(BaseModel):
    """What the API reports about the follow behaviour."""

    enabled: bool = False
    target_label: str = DEFAULT_TARGET_LABEL
    min_confidence: float = 0.5
    target_height: float = 0.7
    max_linear: float = 0.4
    max_angular: float = 0.6
    min_linear: float = 0.15
    face_deadband: float = 0.2
    target_id: int | None = None
    has_target: bool = False
    linear: float = 0.0
    angular: float = 0.0
    lost_s: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def select_target(
    detections: Sequence[Detection],
    *,
    label: str = DEFAULT_TARGET_LABEL,
    min_confidence: float = 0.5,
    lock_id: int | None = None,
) -> Detection | None:
    """Pick the person to follow.

    Prefers the currently locked track (so the rover keeps following the same
    person), otherwise the largest box: the closest person, which is the one the
    operator is most likely to mean.
    """
    candidates = [
        detection
        for detection in detections
        if detection.label == label and detection.confidence >= min_confidence
    ]
    if not candidates:
        return None

    if lock_id is not None:
        for detection in candidates:
            if detection.track_id == lock_id:
                return detection

    return max(candidates, key=lambda d: (d.x_max - d.x_min) * (d.y_max - d.y_min))


def compute_command(target: Detection, tuning: FollowTuning) -> MotionCommand:
    """Turn one target box into a bounded motion command.

    The rover is a **chaser**: it advances whenever the person is ahead and
    roughly centred, and holds a **minimum distance** (``target_height``) so it
    does not run into them.

    - Horizontal error centres the rover: a target to the right makes the rover
      turn right (negative angular; positive angular is left).
    - Forward speed grows with how far the person is (the smaller the box, the
      faster), but only while the person is within ``face_deadband`` of the
      centre. Off to the side, it turns in place instead of driving diagonally.
    - It never reverses: at or beyond the minimum distance it simply stops.
    """
    center_x = (target.x_min + target.x_max) / 2.0
    error_x = center_x - 0.5
    height = target.y_max - target.y_min
    error_size = tuning.target_height - height  # > 0 means "still far"

    angular = 0.0
    if abs(error_x) > tuning.deadband:
        angular = _clamp(-2.0 * tuning.max_angular * error_x, tuning.max_angular)

    linear = 0.0
    if error_size > tuning.deadband and abs(error_x) <= tuning.face_deadband:
        approach = _clamp(2.0 * tuning.max_linear * error_size, tuning.max_linear)
        linear = max(tuning.min_linear, approach)

    return MotionCommand(linear=round(linear, 4), angular=round(angular, 4))


class FollowService:
    """Runs the follow behaviour, one control step at a time."""

    def __init__(
        self,
        rover: RoverService,
        source: Callable[[], DetectionSnapshot],
        *,
        tuning: FollowTuning | None = None,
        interval: float = 0.2,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self._rover = rover
        self._source = source
        self._tuning = tuning or FollowTuning()
        self._interval = interval

        self._enabled = False
        self._task: asyncio.Task[None] | None = None
        self._target_id: int | None = None
        self._has_target = False
        self._last_command = MotionCommand()
        self._lost_since: float | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def tuning(self) -> FollowTuning:
        return self._tuning

    @property
    def status(self) -> FollowStatus:
        lost_s = round(self._now() - self._lost_since, 3) if self._lost_since else None
        return FollowStatus(
            enabled=self._enabled,
            target_label=self._tuning.target_label,
            min_confidence=self._tuning.min_confidence,
            target_height=self._tuning.target_height,
            max_linear=self._tuning.max_linear,
            max_angular=self._tuning.max_angular,
            min_linear=self._tuning.min_linear,
            face_deadband=self._tuning.face_deadband,
            target_id=self._target_id,
            has_target=self._has_target,
            linear=self._last_command.linear,
            angular=self._last_command.angular,
            lost_s=lost_s,
        )

    async def enable(self) -> None:
        """Start following. Idempotent."""
        if self._enabled:
            return
        self._enabled = True
        self._lost_since = None
        logger.info("Follow enabled: looking for '%s'", self._tuning.target_label)
        self._task = asyncio.create_task(self._loop(), name="follow-loop")

    async def disable(self, *, reason: str = "disabled") -> None:
        """Stop following and stop the rover. Always safe to call."""
        self._enabled = False
        await self._cancel()
        await self._rover.stop()
        logger.info("Follow disabled (%s)", reason)

    async def step(self) -> None:
        """Run a single control iteration. Exposed for deterministic tests."""
        snapshot = self._source()
        target = select_target(
            snapshot.detections,
            label=self._tuning.target_label,
            min_confidence=self._tuning.min_confidence,
            lock_id=self._target_id,
        )

        if target is None:
            self._target_id = None
            self._has_target = False
            self._last_command = MotionCommand()
            if self._lost_since is None:
                self._lost_since = self._now()
            # Safety first: stop the moment the target is not visible.
            await self._rover.stop()
            if self._now() - self._lost_since >= self._tuning.lost_timeout:
                logger.warning(
                    "Follow: target lost for %.1fs, disabling", self._tuning.lost_timeout
                )
                self._enabled = False
            return

        self._target_id = target.track_id
        self._has_target = True
        self._lost_since = None
        command = compute_command(target, self._tuning)
        self._last_command = command
        await self._rover.move(command.linear, command.angular)

    # --- Internals -----------------------------------------------------------

    async def _loop(self) -> None:
        try:
            while self._enabled:
                await self.step()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - any failure must stop the rover
            logger.exception("Follow loop failed; stopping the rover")
        finally:
            self._enabled = False
            with suppress(Exception):
                await self._rover.stop()

    async def _cancel(self) -> None:
        task = self._task
        self._task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @staticmethod
    def _now() -> float:
        return time.monotonic()
