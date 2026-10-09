"""Object detection from the IMX500 sensor.

The network runs **inside the sensor** and returns already post-processed tensors
(the model is the `_pp` variant), so there is no NMS to do on the Raspberry Pi.

The geometry is deliberately **not** here. The sensor crops the image according to
its region of interest and the ISP crops it again into the stream, so mapping a
box onto the video frame means undoing both; `IMX500.convert_inference_coords` is
the official helper for that and it needs the frame metadata, which is why it
lives in the camera driver. What this module does is interpret what the network
declares about itself and turn the result into reports.

Measured on the real unit with `ssd_mobilenetv2_fpnlite_320x320_pp`:

    outputs ....... [(1, 100, 4), (1, 100), (1, 100), (1, 1)]
                    boxes (100), scores, classes, valid count
    boxes ......... (y_min, x_min, y_max, x_max), already 0..1
    labels ........ 90 classes
    inference ..... ~26 ms per frame

This module stays free of numpy on purpose: the sensor hands out numpy arrays but
the camera converts them to plain lists, so the logic can be tested anywhere.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.ai.tracking import Tracker

logger = logging.getLogger(__name__)

#: Minimum confidence to report a detection.
DEFAULT_SCORE_THRESHOLD = 0.5

#: How networks usually declare the order of their box coordinates.
DEFAULT_BBOX_ORDER = "yx"


def clamp01(value: float) -> float:
    """Keep a normalised coordinate inside the frame."""
    return min(1.0, max(0.0, value))


class Detection(BaseModel):
    """One detected object, in normalised frame coordinates (0..1)."""

    label: str
    confidence: float = Field(ge=0, le=1)
    #: Bounding box, already mapped onto the frame the operator sees.
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    #: Stable identity across frames, when tracking is enabled.
    track_id: int | None = None


@dataclass(frozen=True)
class InferenceFrame:
    """One inference result, with its boxes already mapped onto the video frame.

    ``boxes`` are ``(x_min, y_min, x_max, y_max)`` normalised to ``0..1``. Getting
    there is the camera's job, because it involves the region of interest the
    sensor used and the crop the ISP applied, and both come from the frame
    metadata.
    """

    boxes: Sequence[Sequence[float]]
    scores: Sequence[float]
    classes: Sequence[float]
    captured_at: float = field(default_factory=time.monotonic)
    dnn_ms: float | None = None
    dsp_ms: float | None = None

    @property
    def age_s(self) -> float:
        return round(time.monotonic() - self.captured_at, 3)


@runtime_checkable
class InferenceSource(Protocol):
    """Whoever can hand out the latest raw inference result."""

    @property
    def detection_labels(self) -> Sequence[str]: ...

    def latest_inference(self) -> InferenceFrame | None: ...


class DetectionSnapshot(BaseModel):
    """What the API reports about the detector."""

    available: bool = False
    model: str | None = None
    labels_count: int = 0
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    tracking: bool = False
    inference_ms: float | None = None
    age_s: float | None = None
    detections: list[Detection] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def normalize_sensor_boxes(
    boxes: Sequence[Sequence[float]],
    *,
    needs_normalization: bool = False,
    order: str = DEFAULT_BBOX_ORDER,
    input_size: tuple[int, int] | None = None,
) -> list[list[float]]:
    """Interpret the network's raw boxes and return frame-ready coordinates.

    A network declares two things about its own boxes, and neither is optional —
    getting either wrong is what makes boxes land in the wrong place:

    - ``needs_normalization`` comes from the ``bbox_normalization`` flag, and its
      name reads **backwards**: when true it means the boxes are in *pixels of the
      input tensor* and have to be divided by its size. When false they already
      arrive in ``0..1``. This is how the official example uses it.
    - ``order`` comes from ``bbox_order``: ``"yx"`` means ``(y0, x0, y1, x1)`` and
      ``"xy"`` means ``(x0, y0, x1, y1)``. Both appear in the wild.

    Everything comes back as ``(x_min, y_min, x_max, y_max)`` in ``0..1``, which is
    what the rest of the application and the browser expect.
    """
    width, height = input_size or (1, 1)
    if width <= 0 or height <= 0:
        width = height = 1

    prepared: list[list[float]] = []
    for box in boxes:
        first, second, third, fourth = (float(value) for value in box)
        if order == "xy":
            x_min, y_min, x_max, y_max = first, second, third, fourth
        else:
            y_min, x_min, y_max, x_max = first, second, third, fourth

        if needs_normalization:
            x_min, x_max = x_min / width, x_max / width
            y_min, y_max = y_min / height, y_max / height

        prepared.append([clamp01(x_min), clamp01(y_min), clamp01(x_max), clamp01(y_max)])

    return prepared


def decode_detections(
    frame: InferenceFrame,
    labels: Sequence[str],
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[Detection]:
    """Turn a converted inference frame into the detections the API reports.

    The camera has already dropped everything below the threshold, so this is
    mainly naming: the network reports class *indices*, the operator wants words.
    """
    detections: list[Detection] = []

    for box, score, class_id in zip(frame.boxes, frame.scores, frame.classes, strict=False):
        confidence = float(score)
        if confidence < score_threshold:
            continue

        x_min, y_min, x_max, y_max = (float(value) for value in box)
        index = int(class_id)
        label = labels[index] if 0 <= index < len(labels) else f"class_{index}"

        detections.append(
            Detection(
                label=label,
                confidence=round(clamp01(confidence), 4),
                x_min=round(x_min, 5),
                y_min=round(y_min, 5),
                x_max=round(x_max, 5),
                y_max=round(y_max, 5),
            )
        )

    detections.sort(key=lambda detection: detection.confidence, reverse=True)
    return detections


class DetectionService:
    """Turns the camera's latest inference into what the API reports."""

    def __init__(
        self,
        source: InferenceSource | None,
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        tracking: bool = True,
        model: str | None = None,
    ) -> None:
        self._source = source
        self._score_threshold = score_threshold
        self._model = model
        self._tracker = Tracker() if tracking else None
        # Snapshot cache: several consumers (API, telemetry, the follow loop) ask
        # for the same frame. Deriving it once per frame keeps the tracker from
        # being advanced several times for a single inference.
        self._last_captured_at: float | None = None
        self._last_snapshot: DetectionSnapshot | None = None

    def set_model(self, model: str | None) -> None:
        """Adopt the reported model after a runtime network switch."""
        self._model = model
        self._last_snapshot = None

    def snapshot(self) -> DetectionSnapshot:
        common = {
            "model": self._model,
            "score_threshold": self._score_threshold,
            "tracking": self._tracker is not None,
        }

        if self._source is None:
            return DetectionSnapshot(available=False, **common)

        labels = self._source.detection_labels
        frame = self._source.latest_inference()

        if frame is None:
            # The sensor has not produced a result yet (it needs a few frames).
            self._last_captured_at = None
            self._last_snapshot = None
            return DetectionSnapshot(available=False, labels_count=len(labels), **common)

        if frame.captured_at == self._last_captured_at and self._last_snapshot is not None:
            return self._last_snapshot

        detections = decode_detections(
            frame,
            labels,
            score_threshold=self._score_threshold,
        )

        if self._tracker is not None:
            observed = self._tracker.update(detections)
            detections = [
                track.detection.model_copy(update={"track_id": track.track_id})
                for track in observed
            ]

        if frame.dnn_ms is not None and frame.dsp_ms is not None:
            inference_ms = round(frame.dnn_ms + frame.dsp_ms, 2)
        else:
            inference_ms = None

        snapshot = DetectionSnapshot(
            available=True,
            labels_count=len(labels),
            inference_ms=inference_ms,
            age_s=frame.age_s,
            detections=detections,
            **common,
        )
        self._last_captured_at = frame.captured_at
        self._last_snapshot = snapshot
        return snapshot
