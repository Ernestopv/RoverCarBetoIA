"""Tests for the detection decoding.

The geometry is **not** tested here. Mapping the sensor's boxes onto the video
frame is picamera2's job (`convert_inference_coords`) and belongs to the camera
driver, because it needs the frame metadata. What is tested here is the part that
is ours: interpreting what the network declares about its own boxes, and turning
the values into reports.
"""

from __future__ import annotations

import pytest

from app.ai.detection import (
    DetectionService,
    InferenceFrame,
    normalize_sensor_boxes,
)

LABELS = ("person", "bicycle", "car", "motorcycle")

#: Measured on the unit for `ssd_mobilenetv2_fpnlite_320x320_pp`.
INPUT_SIZE = (320, 320)

#: The network offers a fixed number of slots and leaves most of them empty.
_SLOTS = 100


def frame_of(
    detections: list[tuple[float, float, float, float, float, int]],
) -> InferenceFrame:
    """Build a frame shaped like the sensor's.

    Boxes are written as ``(x_min, y_min, x_max, y_max)`` because that is the form
    the camera produces once it has converted them for the frame.
    """
    boxes: list[list[float]] = []
    scores: list[float] = []
    classes: list[float] = []

    for x_min, y_min, x_max, y_max, score, class_id in detections:
        boxes.append([x_min, y_min, x_max, y_max])
        scores.append(score)
        classes.append(float(class_id))

    while len(boxes) < _SLOTS:
        boxes.append([0.0, 0.0, 0.0, 0.0])
        scores.append(0.0)
        classes.append(0.0)

    return InferenceFrame(boxes=boxes, scores=scores, classes=classes)


# --- interpreting what the network declares -----------------------------------


def test_the_default_order_is_y0_x0_y1_x1() -> None:
    prepared = normalize_sensor_boxes([[0.1, 0.2, 0.3, 0.4]])

    # (y0, x0, y1, x1) -> (x_min, y_min, x_max, y_max)
    assert prepared[0] == pytest.approx([0.2, 0.1, 0.4, 0.3])


def test_the_xy_order_is_kept_as_it_arrives() -> None:
    prepared = normalize_sensor_boxes([[0.2, 0.1, 0.4, 0.3]], order="xy")

    assert prepared[0] == pytest.approx([0.2, 0.1, 0.4, 0.3])


def test_a_network_that_asks_for_normalisation_gets_its_boxes_divided() -> None:
    """`bbox_normalization: true` means "these are pixels, normalise them"."""
    prepared = normalize_sensor_boxes(
        [[32.0, 64.0, 96.0, 128.0]],  # (y0, x0, y1, x1) in 320-space
        needs_normalization=True,
        input_size=INPUT_SIZE,
    )

    assert prepared[0] == pytest.approx([0.2, 0.1, 0.4, 0.3])


def test_a_network_that_does_not_asks_for_it_is_left_alone() -> None:
    """This is the SSD-MobileNetV2 case: it already returns 0..1."""
    prepared = normalize_sensor_boxes(
        [[0.2, 0.1, 0.4, 0.3]],  # (y0, x0, y1, x1), already 0..1
        needs_normalization=False,
        input_size=INPUT_SIZE,
    )

    # Only the order is rearranged; the values are untouched.
    assert prepared[0] == pytest.approx([0.1, 0.2, 0.3, 0.4])


def test_normalisation_uses_each_axis_size_separately() -> None:
    """Not a square input: dividing both axes by the same number would skew it."""
    prepared = normalize_sensor_boxes(
        [[0.0, 160.0, 160.0, 320.0]],  # (y0, x0, y1, x1)
        needs_normalization=True,
        input_size=(320, 160),
    )

    # x: 160/320 = 0.5 .. 320/320 = 1.0
    # y: 0/160 = 0.0   .. 160/160 = 1.0
    assert prepared[0] == pytest.approx([0.5, 0.0, 1.0, 1.0])


def test_boxes_are_clamped_to_the_frame() -> None:
    prepared = normalize_sensor_boxes([[-10.0, -20.0, 400.0, 500.0]])

    assert prepared[0] == pytest.approx([0.0, 0.0, 1.0, 1.0])


def test_no_boxes_is_not_an_error() -> None:
    assert normalize_sensor_boxes([]) == []


# --- reporting ----------------------------------------------------------------


def test_keeps_only_confident_detections() -> None:
    frame = frame_of(
        [
            (0.1, 0.1, 0.5, 0.5, 0.91, 0),  # person
            (0.2, 0.2, 0.6, 0.6, 0.20, 2),  # car, below threshold
        ]
    )

    detections = DetectionService(FakeCamera(frame)).snapshot().detections

    assert len(detections) == 1
    assert detections[0].label == "person"
    assert detections[0].confidence == pytest.approx(0.91)


def test_detections_are_sorted_by_confidence() -> None:
    frame = frame_of(
        [
            (0.1, 0.1, 0.2, 0.2, 0.55, 0),
            (0.3, 0.3, 0.4, 0.4, 0.99, 2),
            (0.5, 0.5, 0.6, 0.6, 0.70, 1),
        ]
    )

    detections = DetectionService(FakeCamera(frame)).snapshot().detections

    assert [d.label for d in detections] == ["car", "bicycle", "person"]


def test_boxes_are_reported_as_x_min_y_min_x_max_y_max() -> None:
    frame = frame_of([(0.2, 0.1, 0.4, 0.3, 0.9, 0)])

    detection = DetectionService(FakeCamera(frame)).snapshot().detections[0]

    assert detection.x_min == pytest.approx(0.2)
    assert detection.y_min == pytest.approx(0.1)
    assert detection.x_max == pytest.approx(0.4)
    assert detection.y_max == pytest.approx(0.3)


def test_an_unknown_class_index_does_not_crash() -> None:
    frame = frame_of([(0.1, 0.1, 0.2, 0.2, 0.9, 99)])

    detection = DetectionService(FakeCamera(frame)).snapshot().detections[0]

    assert detection.label == "class_99"


def test_all_zero_padding_produces_no_detections() -> None:
    assert DetectionService(FakeCamera(frame_of([]))).snapshot().detections == []


def test_every_reported_box_is_valid_and_ordered() -> None:
    """Regression: the raw sensor boxes once leaked out as negative numbers."""
    frame = frame_of(
        [
            (0.2, 0.1, 0.6, 0.5, 0.9, 0),
            (0.0, 0.0, 1.0, 1.0, 0.8, 2),
            (0.4, 0.4, 0.95, 0.9, 0.7, 1),
        ]
    )

    for detection in DetectionService(FakeCamera(frame)).snapshot().detections:
        assert 0.0 <= detection.x_min < detection.x_max <= 1.0
        assert 0.0 <= detection.y_min < detection.y_max <= 1.0


# --- service ------------------------------------------------------------------


class FakeCamera:
    """Stands in for the IMX500 driver."""

    def __init__(self, frame: InferenceFrame | None, labels: tuple[str, ...] = LABELS) -> None:
        self._frame = frame
        self._labels = labels

    @property
    def detection_labels(self) -> tuple[str, ...]:
        return self._labels

    def latest_inference(self) -> InferenceFrame | None:
        return self._frame


def test_service_reports_unavailable_without_a_source() -> None:
    snapshot = DetectionService(None).snapshot()

    assert snapshot.available is False
    assert snapshot.detections == []


def test_service_reports_unavailable_before_the_first_inference() -> None:
    snapshot = DetectionService(FakeCamera(None), model="model.rpk").snapshot()

    assert snapshot.available is False
    assert snapshot.model == "model.rpk"
    assert snapshot.labels_count == len(LABELS)


def test_service_exposes_detections_and_inference_time() -> None:
    frame = InferenceFrame(
        boxes=[[0.1, 0.1, 0.4, 0.4]],
        scores=[0.88],
        classes=[0.0],
        dnn_ms=17.4,
        dsp_ms=8.6,
    )

    snapshot = DetectionService(FakeCamera(frame)).snapshot()

    assert snapshot.available is True
    assert snapshot.inference_ms == pytest.approx(26.0)  # 17.4 DNN + 8.6 DSP
    assert [d.label for d in snapshot.detections] == ["person"]


def test_service_assigns_stable_track_ids() -> None:
    frame = frame_of([(0.2, 0.1, 0.4, 0.3, 0.9, 0)])
    service = DetectionService(FakeCamera(frame))

    first = service.snapshot().detections[0].track_id
    second = service.snapshot().detections[0].track_id

    assert first is not None
    assert first == second


def test_snapshot_is_derived_once_per_frame() -> None:
    """Several consumers (API, telemetry, follow loop) ask for the same frame.

    Deriving the snapshot more than once would advance the tracker several times
    for a single inference, so the cache returns the same object.
    """
    frame = frame_of([(0.2, 0.1, 0.4, 0.3, 0.9, 0)])
    service = DetectionService(FakeCamera(frame))

    assert service.snapshot() is service.snapshot()


def test_a_new_frame_is_processed_again() -> None:
    class SwappableCamera(FakeCamera):
        def set_frame(self, frame: InferenceFrame) -> None:
            self._frame = frame

    camera = SwappableCamera(frame_of([(0.2, 0.1, 0.4, 0.3, 0.9, 0)]))
    service = DetectionService(camera)

    first = service.snapshot()
    camera.set_frame(
        InferenceFrame(
            boxes=[[0.21, 0.1, 0.41, 0.3]],
            scores=[0.9],
            classes=[0.0],
            captured_at=10_000_000.0,
        )
    )
    second = service.snapshot()

    assert second is not first
    assert second.detections[0].track_id == first.detections[0].track_id


def test_tracking_can_be_turned_off() -> None:
    frame = frame_of([(0.2, 0.1, 0.4, 0.3, 0.9, 0)])

    snapshot = DetectionService(FakeCamera(frame), tracking=False).snapshot()

    assert snapshot.tracking is False
    assert snapshot.detections[0].track_id is None


def test_a_real_camera_is_recognised_as_an_inference_source() -> None:
    from app.ai.detection import InferenceSource
    from app.camera.imx500 import Imx500Camera

    camera = Imx500Camera(
        network_file="model.rpk",
        rtsp_url="rtsp://mediamtx:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
    )

    assert isinstance(camera, InferenceSource)
    assert camera.latest_inference() is None
    assert camera.detection_labels == ()
