"""Give detections a stable identity across frames.

The sensor runs at 23 inferences per second and knows nothing about time: every
frame is an independent list of boxes. Without identity, the interface cannot say
"the person is still the person", and a later behaviour layer cannot follow
anything.

The matching is deliberately simple and dependency-free: greedy IoU between boxes
of the same label, plus a grace period so a track survives a frame or two where
the object is momentarily missed (occlusion, motion blur, a dip in confidence).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported for typing only: `detection` imports this module
    from app.ai.detection import Detection

#: Minimum overlap for two boxes to be considered the same object.
DEFAULT_IOU_THRESHOLD = 0.3
#: Frames a track survives without being seen before it is dropped.
DEFAULT_MAX_MISSED = 8


def iou(a: Detection, b: Detection) -> float:
    """Intersection over union of two normalised boxes, in ``0..1``."""
    x_left = max(a.x_min, b.x_min)
    y_top = max(a.y_min, b.y_min)
    x_right = min(a.x_max, b.x_max)
    y_bottom = min(a.y_max, b.y_max)

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0

    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = (a.x_max - a.x_min) * (a.y_max - a.y_min)
    area_b = (b.x_max - b.x_min) * (b.y_max - b.y_min)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


@dataclass
class Track:
    """One object followed across frames."""

    track_id: int
    detection: Detection
    #: Frames in which this track has been seen.
    age: int = 1
    #: Consecutive frames since it was last seen.
    missed: int = 0


@dataclass
class Tracker:
    """Greedy IoU tracker with a grace period."""

    iou_threshold: float = DEFAULT_IOU_THRESHOLD
    max_missed: int = DEFAULT_MAX_MISSED
    _tracks: list[Track] = field(default_factory=list)
    _ids: Iterator[int] = field(default_factory=lambda: count(1))

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    def update(self, detections: Sequence[Detection]) -> list[Track]:
        """Match detections against live tracks and return the observed ones.

        Tracks that were not observed this frame are kept internally (so a
        momentarily hidden object gets its identity back) but are *not* returned:
        the caller must not draw boxes for things that were not detected.
        """
        # Best overlaps first, so a strong match wins over a weak one.
        candidates: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self._tracks):
            for detection_index, detection in enumerate(detections):
                if detection.label != track.detection.label:
                    continue
                score = iou(track.detection, detection)
                if score >= self.iou_threshold:
                    candidates.append((score, track_index, detection_index))
        candidates.sort(reverse=True)

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        observed: list[Track] = []

        for _, track_index, detection_index in candidates:
            if track_index in matched_tracks or detection_index in matched_detections:
                continue
            matched_tracks.add(track_index)
            matched_detections.add(detection_index)

            track = self._tracks[track_index]
            track.detection = detections[detection_index]
            track.age += 1
            track.missed = 0
            observed.append(track)

        survivors: list[Track] = []
        for track_index, track in enumerate(self._tracks):
            if track_index in matched_tracks:
                survivors.append(track)
                continue
            track.missed += 1
            if track.missed <= self.max_missed:
                survivors.append(track)

        for detection_index, detection in enumerate(detections):
            if detection_index in matched_detections:
                continue
            # A brand new track was seen this frame, so it is observed too.
            track = Track(track_id=next(self._ids), detection=detection)
            survivors.append(track)
            observed.append(track)

        self._tracks = survivors
        return observed

    def reset(self) -> None:
        self._tracks.clear()
        self._ids = count(1)
