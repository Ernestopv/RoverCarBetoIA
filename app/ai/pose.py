"""Pose estimation from the IMX500 sensor.

The network running is `higherhrnet_coco`, which marks 17 joints on up to 30
people. Like detection, the work happens **inside the sensor**: this model is
post-processed on board, so what arrives is already grouped into people. All that
is left is naming the joints, dropping the ones the network did not really find,
and reporting.

The joint names and the skeleton are the COCO convention and are fixed by the
network's training, not read from anywhere.

Measured on the real unit:

    outputs ....... three tensors of (1, 30, 17)
    layout ........ tags, indices, confidences
    joints ........ 17 per person, up to 30 people
    inference ..... ~100 ms per frame (10 per second)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Minimum confidence for a joint to be reported.
DEFAULT_KEYPOINT_THRESHOLD = 0.2

#: Minimum confidence for a person to be reported.
DEFAULT_PERSON_THRESHOLD = 0.3

#: The 17 joints of the COCO keypoint convention, in the order the network emits.
KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

#: Which joints are joined by a bone. Drawn, not computed with.
SKELETON = (
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (12, 14),
    (13, 15),
    (14, 16),
)


class Keypoint(BaseModel):
    """One joint, in normalised frame coordinates (0..1)."""

    name: str
    x: float
    y: float
    confidence: float = Field(ge=0, le=1)


class PosePerson(BaseModel):
    """One person, as the API reports them.

    Named `PosePerson` rather than `Pose` on purpose: the rover status has a
    `Pose` of its own (position and heading), and two different things with the
    same name in one API is a trap.
    """

    confidence: float = Field(ge=0, le=1)
    #: Bounding box derived from the joints, mapped onto the frame.
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    #: Only the joints the network was confident about.
    keypoints: list[Keypoint] = Field(default_factory=list)


class PoseSnapshot(BaseModel):
    """What the API reports about pose estimation."""

    available: bool = False
    model: str | None = None
    keypoint_names: list[str] = Field(default_factory=lambda: list(KEYPOINT_NAMES))
    skeleton: list[list[int]] = Field(default_factory=lambda: [list(bone) for bone in SKELETON])
    person_threshold: float = DEFAULT_PERSON_THRESHOLD
    keypoint_threshold: float = DEFAULT_KEYPOINT_THRESHOLD
    inference_ms: float | None = None
    age_s: float | None = None
    people: list[PosePerson] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PoseObservation:
    """One person, exactly as the camera hands them over.

    Everything is already in normalised frame coordinates: mapping the network's
    output onto the video is the camera's job, because it needs the frame metadata.

    The bounding box is deliberately **not** carried: the network reports it in
    ``(y, x, y, x)`` order while the joints come in ``(x, y)``, and deriving it
    from the joints instead gives the same result without that trap.
    """

    score: float
    #: 17 ``(x, y, confidence)`` triples, in :data:`KEYPOINT_NAMES` order.
    keypoints: Sequence[tuple[float, float, float]]


@dataclass(frozen=True)
class PoseFrame:
    """One pose inference result."""

    people: Sequence[PoseObservation]
    captured_at: float = field(default_factory=time.monotonic)
    dnn_ms: float | None = None
    dsp_ms: float | None = None

    @property
    def age_s(self) -> float:
        return round(time.monotonic() - self.captured_at, 3)


@runtime_checkable
class PoseSource(Protocol):
    """Whoever can hand out the latest pose result."""

    def latest_pose(self) -> PoseFrame | None: ...


def _joints_of(observation: PoseObservation, threshold: float) -> list[Keypoint]:
    """Keep the joints the network was actually confident about.

    The network returns all 17 every time, filling in ``(0, 0, 0)`` for the ones it
    did not find. Reporting those would draw a skeleton with limbs going to the
    corner of the picture.
    """
    joints: list[Keypoint] = []
    for index, (x, y, confidence) in enumerate(observation.keypoints):
        value = float(confidence)
        if value < threshold or value <= 0.0:
            continue
        joints.append(
            Keypoint(
                name=KEYPOINT_NAMES[index] if index < len(KEYPOINT_NAMES) else f"joint_{index}",
                x=round(float(x), 5),
                y=round(float(y), 5),
                confidence=round(min(1.0, max(0.0, value)), 4),
            )
        )
    return joints


def _drop_coincident(joints: Sequence[Keypoint]) -> list[Keypoint]:
    """Drop joints that claim exactly the same point as another one.

    Two *different* joints of one person cannot occupy the same spot, so when the
    network says they do, it did not really find them.

    Measured on the unit: with the feet below the bottom of the frame, both ankles
    came back at ``(0.381, 0.995)`` with the same confidence. Drawn as-is, the two
    legs met at a single point and the skeleton looked like the legs joined.

    Both are dropped rather than one: if the network cannot tell them apart, there
    is no way to know which of the two, if either, is the real one.
    """
    counts: dict[tuple[float, float], int] = {}
    for joint in joints:
        counts[(joint.x, joint.y)] = counts.get((joint.x, joint.y), 0) + 1
    return [joint for joint in joints if counts[(joint.x, joint.y)] == 1]


def _box_around(joints: Sequence[Keypoint]) -> tuple[float, float, float, float]:
    """The smallest box that contains the joints we are going to draw."""
    xs = [joint.x for joint in joints]
    ys = [joint.y for joint in joints]
    return min(xs), min(ys), max(xs), max(ys)


def _person_of(observation: PoseObservation, keypoint_threshold: float) -> PosePerson | None:
    """Build the report for one person, or ``None`` if nothing was found on them."""
    joints = _drop_coincident(_joints_of(observation, keypoint_threshold))
    if not joints:
        # No joint was clear enough: there is nothing to show or to follow.
        return None

    x_min, y_min, x_max, y_max = _box_around(joints)
    return PosePerson(
        confidence=round(min(1.0, max(0.0, float(observation.score))), 4),
        x_min=round(x_min, 5),
        y_min=round(y_min, 5),
        x_max=round(x_max, 5),
        y_max=round(y_max, 5),
        keypoints=joints,
    )


class PoseService:
    """Turns the camera's latest pose result into what the API reports."""

    def __init__(
        self,
        source: PoseSource | None,
        *,
        person_threshold: float = DEFAULT_PERSON_THRESHOLD,
        keypoint_threshold: float = DEFAULT_KEYPOINT_THRESHOLD,
        model: str | None = None,
    ) -> None:
        self._source = source
        self._person_threshold = person_threshold
        self._keypoint_threshold = keypoint_threshold
        self._model = model

    def set_model(self, model: str | None) -> None:
        """Adopt the reported model after a runtime network switch."""
        self._model = model

    def snapshot(self) -> PoseSnapshot:
        common = {
            "model": self._model,
            "person_threshold": self._person_threshold,
            "keypoint_threshold": self._keypoint_threshold,
        }

        if self._source is None:
            return PoseSnapshot(available=False, **common)

        frame = self._source.latest_pose()
        if frame is None:
            # Either the network is not a pose one, or it has not produced a
            # result yet.
            return PoseSnapshot(available=False, **common)

        people = [
            person
            for person in (
                _person_of(observation, self._keypoint_threshold)
                for observation in frame.people
                if float(observation.score) >= self._person_threshold
            )
            if person is not None
        ]
        people.sort(key=lambda person: person.confidence, reverse=True)

        if frame.dnn_ms is not None and frame.dsp_ms is not None:
            inference_ms = round(frame.dnn_ms + frame.dsp_ms, 2)
        else:
            inference_ms = None

        return PoseSnapshot(
            available=True,
            inference_ms=inference_ms,
            age_s=frame.age_s,
            people=people,
            **common,
        )
