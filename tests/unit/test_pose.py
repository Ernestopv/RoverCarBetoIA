"""Tests for the pose reporting.

The decoding itself is picamera2's, and mapping the joints onto the video frame is
the camera driver's because it needs the frame metadata. What is tested here is
what is ours: which joints are worth reporting, what to do with the ones the
network did not really find, and how a person is described.
"""

from __future__ import annotations

import pytest

from app.ai.pose import (
    DEFAULT_KEYPOINT_THRESHOLD,
    KEYPOINT_NAMES,
    SKELETON,
    PoseFrame,
    PoseObservation,
    PoseService,
)

#: A person used when only the threshold behaviour matters.
SCORE = 0.8


def observation(score: float = SCORE, **joints: tuple[float, float, float]) -> PoseObservation:
    """Build a person with all 17 joints, overriding only the ones named.

    The network always returns 17 joints and fills in ``(0, 0, 0)`` for the ones it
    did not find, so that is the starting point here too.
    """
    points: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)] * len(KEYPOINT_NAMES)
    for name, value in joints.items():
        points[KEYPOINT_NAMES.index(name)] = value
    return PoseObservation(score=score, keypoints=points)


class FakeCamera:
    """Stands in for the IMX500 driver."""

    def __init__(self, frame: PoseFrame | None) -> None:
        self._frame = frame

    def latest_pose(self) -> PoseFrame | None:
        return self._frame


# --- joints the network did not find ------------------------------------------


def test_joints_left_at_zero_are_not_reported() -> None:
    """Otherwise every skeleton would have limbs reaching the corner of the frame."""
    frame = PoseFrame(people=[observation(nose=(0.5, 0.1, 0.9))])

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    assert [joint.name for joint in person.keypoints] == ["nose"]


def test_joints_below_the_threshold_are_dropped() -> None:
    frame = PoseFrame(people=[observation(nose=(0.5, 0.1, 0.9), left_eye=(0.45, 0.12, 0.05))])

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    assert [joint.name for joint in person.keypoints] == ["nose"]


def test_a_person_without_any_clear_joint_is_dropped() -> None:
    """There is nothing to draw and nothing to follow."""
    frame = PoseFrame(people=[observation(nose=(0.5, 0.1, 0.01))])

    assert PoseService(FakeCamera(frame)).snapshot().people == []


def test_joints_claiming_the_same_point_are_both_dropped() -> None:
    """Measured: with the feet off frame, both ankles came back identical.

    Drawn as-is they made the two legs meet at one point.
    """
    frame = PoseFrame(
        people=[
            observation(
                nose=(0.50, 0.10, 0.90),
                left_knee=(0.45, 0.80, 0.60),
                right_knee=(0.55, 0.80, 0.60),
                left_ankle=(0.381, 0.995, 0.38),
                right_ankle=(0.381, 0.995, 0.38),
            )
        ]
    )

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    names = [joint.name for joint in person.keypoints]
    assert "left_ankle" not in names
    assert "right_ankle" not in names
    # The joints that do make sense are untouched.
    assert "left_knee" in names
    assert "nose" in names


def test_a_coincident_joint_does_not_stretch_the_box() -> None:
    frame = PoseFrame(
        people=[
            observation(
                left_knee=(0.45, 0.80, 0.60),
                right_knee=(0.55, 0.80, 0.60),
                left_ankle=(0.99, 0.99, 0.30),
                right_ankle=(0.99, 0.99, 0.30),
            )
        ]
    )

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    assert person.x_max == pytest.approx(0.55)
    assert person.y_max == pytest.approx(0.80)


def test_joints_that_are_merely_close_are_kept() -> None:
    """Only identical points are suspect: feet together is a real pose."""
    frame = PoseFrame(
        people=[observation(left_ankle=(0.40, 0.90, 0.70), right_ankle=(0.42, 0.90, 0.70))]
    )

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    assert len(person.keypoints) == 2


# --- describing a person ------------------------------------------------------


def test_the_box_is_derived_from_the_reported_joints() -> None:
    frame = PoseFrame(
        people=[
            observation(
                left_shoulder=(0.30, 0.40, 0.9),
                right_shoulder=(0.70, 0.42, 0.9),
                left_ankle=(0.35, 0.95, 0.9),
            )
        ]
    )

    person = PoseService(FakeCamera(frame)).snapshot().people[0]

    assert (person.x_min, person.y_min) == pytest.approx((0.30, 0.40))
    assert (person.x_max, person.y_max) == pytest.approx((0.70, 0.95))


def test_people_are_sorted_by_confidence() -> None:
    frame = PoseFrame(
        people=[
            observation(score=0.4, nose=(0.1, 0.1, 0.9)),
            observation(score=0.9, nose=(0.5, 0.5, 0.9)),
            observation(score=0.6, nose=(0.8, 0.8, 0.9)),
        ]
    )

    people = PoseService(FakeCamera(frame)).snapshot().people

    assert [person.confidence for person in people] == pytest.approx([0.9, 0.6, 0.4])


def test_people_below_the_person_threshold_are_dropped() -> None:
    frame = PoseFrame(
        people=[
            observation(score=0.5, nose=(0.1, 0.1, 0.9)),
            observation(score=0.1, nose=(0.5, 0.5, 0.9)),
        ]
    )

    people = PoseService(FakeCamera(frame), person_threshold=0.3).snapshot().people

    assert len(people) == 1


def test_several_people_are_all_reported() -> None:
    frame = PoseFrame(
        people=[
            observation(score=0.9, nose=(0.2, 0.2, 0.9)),
            observation(score=0.8, nose=(0.7, 0.3, 0.9)),
        ]
    )

    assert len(PoseService(FakeCamera(frame)).snapshot().people) == 2


def test_an_empty_frame_is_available_but_has_no_people() -> None:
    """No person in view is a valid answer, not a failure."""
    snapshot = PoseService(FakeCamera(PoseFrame(people=[]))).snapshot()

    assert snapshot.available is True
    assert snapshot.people == []


# --- the snapshot -------------------------------------------------------------


def test_the_snapshot_carries_the_names_and_the_skeleton() -> None:
    """So the interface does not have to hard-code the COCO convention."""
    snapshot = PoseService(None).snapshot()

    assert snapshot.keypoint_names == list(KEYPOINT_NAMES)
    assert [tuple(bone) for bone in snapshot.skeleton] == list(SKELETON)


def test_the_skeleton_only_names_real_joints() -> None:
    for start, end in SKELETON:
        assert 0 <= start < len(KEYPOINT_NAMES)
        assert 0 <= end < len(KEYPOINT_NAMES)
        assert start != end


def test_service_reports_unavailable_without_a_source() -> None:
    snapshot = PoseService(None).snapshot()

    assert snapshot.available is False
    assert snapshot.people == []


def test_service_reports_unavailable_before_the_first_result() -> None:
    snapshot = PoseService(FakeCamera(None), model="higherhrnet.rpk").snapshot()

    assert snapshot.available is False
    assert snapshot.model == "higherhrnet.rpk"


def test_service_exposes_inference_time() -> None:
    frame = PoseFrame(
        people=[observation(nose=(0.5, 0.1, 0.9))],
        dnn_ms=60.0,
        dsp_ms=40.0,
    )

    snapshot = PoseService(FakeCamera(frame)).snapshot()

    assert snapshot.inference_ms == pytest.approx(100.0)


def test_the_keypoint_threshold_is_configurable() -> None:
    frame = PoseFrame(people=[observation(nose=(0.5, 0.1, 0.35), left_eye=(0.45, 0.1, 0.9))])

    strict = PoseService(FakeCamera(frame), keypoint_threshold=0.5).snapshot()

    assert [joint.name for joint in strict.people[0].keypoints] == ["left_eye"]
    assert DEFAULT_KEYPOINT_THRESHOLD < 0.5


def test_a_real_camera_is_recognised_as_a_pose_source() -> None:
    from app.ai.pose import PoseSource
    from app.camera.imx500 import Imx500Camera

    camera = Imx500Camera(
        network_file="model.rpk",
        rtsp_url="rtsp://mediamtx:8554/rover",
        stream_path="rover",
        webrtc_port=8889,
    )

    assert isinstance(camera, PoseSource)
    # No pose result until a pose network is loaded and running.
    assert camera.latest_pose() is None
