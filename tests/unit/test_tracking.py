"""Tests for the tracker.

Everything here is pure geometry: no camera, no numpy, no timing.
"""

from __future__ import annotations

import pytest

from app.ai.detection import Detection
from app.ai.tracking import Tracker, iou


def box(label: str, x: float, y: float, size: float = 0.2, confidence: float = 0.9) -> Detection:
    return Detection(
        label=label,
        confidence=confidence,
        x_min=x,
        y_min=y,
        x_max=x + size,
        y_max=y + size,
    )


# --- IoU ----------------------------------------------------------------------


def test_identical_boxes_overlap_completely() -> None:
    assert iou(box("person", 0.1, 0.1), box("person", 0.1, 0.1)) == pytest.approx(1.0)


def test_boxes_that_do_not_touch_score_zero() -> None:
    assert iou(box("person", 0.0, 0.0), box("person", 0.5, 0.5)) == 0.0


def test_half_overlap_is_between_zero_and_one() -> None:
    score = iou(box("person", 0.0, 0.0, 0.2), box("person", 0.1, 0.0, 0.2))

    # Intersection 0.1*0.2 = 0.02, union 0.04 + 0.04 - 0.02 = 0.06.
    assert score == pytest.approx(0.3333, abs=1e-3)


def test_a_degenerate_box_does_not_divide_by_zero() -> None:
    assert iou(box("person", 0.1, 0.1, 0.0), box("person", 0.1, 0.1, 0.0)) == 0.0


# --- tracking -----------------------------------------------------------------


def test_a_new_object_gets_a_new_id() -> None:
    tracker = Tracker()

    observed = tracker.update([box("person", 0.1, 0.1)])

    assert len(observed) == 1
    assert observed[0].track_id == 1
    assert observed[0].age == 1


def test_the_same_object_keeps_its_id_when_it_moves() -> None:
    tracker = Tracker()
    first = tracker.update([box("person", 0.10, 0.10)])[0].track_id

    second = tracker.update([box("person", 0.13, 0.10)])[0]

    assert second.track_id == first
    assert second.age == 2


def test_two_objects_get_different_ids() -> None:
    tracker = Tracker()

    observed = tracker.update([box("person", 0.0, 0.0), box("car", 0.6, 0.6)])

    assert len({track.track_id for track in observed}) == 2


def test_a_different_label_is_never_matched() -> None:
    tracker = Tracker()
    person = tracker.update([box("person", 0.1, 0.1)])[0].track_id

    observed = tracker.update([box("car", 0.1, 0.1)])[0]

    assert observed.track_id != person


def test_identity_survives_a_brief_disappearance() -> None:
    """Occlusion or a confidence dip must not create a new object."""
    tracker = Tracker(max_missed=3)
    original = tracker.update([box("person", 0.1, 0.1)])[0].track_id

    tracker.update([])  # missed one frame
    tracker.update([])
    observed = tracker.update([box("person", 0.1, 0.1)])

    assert observed[0].track_id == original
    assert observed[0].age == 2  # only counts frames actually seen


def test_a_track_is_dropped_after_too_many_misses() -> None:
    tracker = Tracker(max_missed=2)
    original = tracker.update([box("person", 0.1, 0.1)])[0].track_id

    for _ in range(3):
        tracker.update([])
    observed = tracker.update([box("person", 0.1, 0.1)])

    assert observed[0].track_id != original
    assert tracker.track_count == 1


def test_unobserved_tracks_are_not_returned() -> None:
    """The interface must not draw boxes for objects that were not detected."""
    tracker = Tracker()
    tracker.update([box("person", 0.1, 0.1)])

    assert tracker.update([]) == []


def test_the_best_overlap_wins_the_match() -> None:
    tracker = Tracker()
    original = tracker.update([box("person", 0.0, 0.0, 0.2)])[0].track_id

    # An exact overlap and a partial one: the exact one must win.
    observed = tracker.update([box("person", 0.0, 0.0, 0.2), box("person", 0.1, 0.0, 0.2)])

    matched = next(track for track in observed if track.track_id == original)
    assert matched.detection.x_min == pytest.approx(0.0)


def test_reset_forgets_everything() -> None:
    tracker = Tracker()
    tracker.update([box("person", 0.1, 0.1)])

    tracker.reset()

    assert tracker.track_count == 0
    assert tracker.update([box("person", 0.1, 0.1)])[0].track_id == 1
