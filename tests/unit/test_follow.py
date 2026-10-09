"""Tests for the person-following behaviour (Phase 7).

Everything here is pure geometry plus a service driven by fakes: no camera, no
rover, no timing. The behaviour must be safe to test with no hardware and must
never produce motion in the test suite unless a test drives it explicitly.
"""

from __future__ import annotations

from app.ai.detection import Detection, DetectionSnapshot
from app.ai.follow import (
    FollowService,
    FollowTuning,
    compute_command,
    select_target,
)

# --- target selection ---------------------------------------------------------


def person(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    *,
    confidence: float = 0.9,
    track_id: int | None = None,
    label: str = "person",
) -> Detection:
    return Detection(
        label=label,
        confidence=confidence,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        track_id=track_id,
    )


def snapshot(*detections: Detection) -> DetectionSnapshot:
    return DetectionSnapshot(available=True, detections=list(detections))


def test_selects_the_largest_person() -> None:
    small = person(0.0, 0.0, 0.1, 0.1)
    big = person(0.3, 0.3, 0.9, 0.9)

    assert select_target([small, big]) is big


def test_ignores_labels_other_than_the_target() -> None:
    car = person(0.0, 0.0, 1.0, 1.0, label="car")
    human = person(0.1, 0.1, 0.2, 0.2)

    assert select_target([car, human]) is human


def test_ignores_detections_below_the_confidence_threshold() -> None:
    weak = person(0.0, 0.0, 1.0, 1.0, confidence=0.2)

    assert select_target([weak], min_confidence=0.5) is None


def test_no_candidates_returns_none() -> None:
    assert select_target([]) is None


def test_prefers_the_locked_track() -> None:
    locked = person(0.0, 0.0, 0.2, 0.2, track_id=7)
    bigger = person(0.3, 0.3, 0.9, 0.9, track_id=8)

    assert select_target([locked, bigger], lock_id=7) is locked


def test_falls_back_to_the_largest_when_the_lock_is_gone() -> None:
    bigger = person(0.3, 0.3, 0.9, 0.9, track_id=8)

    assert select_target([bigger], lock_id=7) is bigger


# --- command geometry ---------------------------------------------------------


def test_a_centred_target_at_the_minimum_distance_stops() -> None:
    tuning = FollowTuning(target_height=0.7)
    close = person(0.1, 0.1, 0.9, 0.9)  # height 0.8, centre x 0.5

    command = compute_command(close, tuning)

    assert command.linear == 0.0
    assert command.angular == 0.0


def test_a_centred_distant_target_advances() -> None:
    # The chaser case: person ahead, centred and small -> drive toward them.
    command = compute_command(person(0.45, 0.45, 0.55, 0.55), FollowTuning())

    assert command.linear > 0
    assert command.angular == 0.0


def test_a_target_off_to_the_side_turns_without_driving() -> None:
    # Off to the side: turn to face them, but do not drive diagonally.
    command = compute_command(person(0.8, 0.45, 0.95, 0.55), FollowTuning())

    assert command.linear == 0.0
    assert command.angular < 0


def test_forward_speed_keeps_a_floor() -> None:
    tuning = FollowTuning(target_height=0.5, deadband=0.06, min_linear=0.2, max_linear=0.4)
    slightly_far = person(0.45, 0.29, 0.55, 0.71)  # height 0.42, centre x 0.5

    command = compute_command(slightly_far, tuning)

    assert command.linear == 0.2


def test_a_target_on_the_right_turns_right() -> None:
    # Positive angular is left, so a target on the right must give a negative one.
    command = compute_command(person(0.7, 0.25, 0.95, 0.75), FollowTuning())

    assert command.angular < 0


def test_a_target_on_the_left_turns_left() -> None:
    command = compute_command(person(0.05, 0.25, 0.3, 0.75), FollowTuning())

    assert command.angular > 0


def test_a_distant_target_moves_forward() -> None:
    # A small box (far away) is below the desired height, so approach.
    command = compute_command(person(0.4, 0.4, 0.6, 0.6), FollowTuning(target_height=0.5))

    assert command.linear > 0


def test_a_close_target_never_reverses() -> None:
    # A big box means "too close": the rover stops, it does not back up blindly.
    command = compute_command(person(0.0, 0.0, 1.0, 1.0), FollowTuning(target_height=0.5))

    assert command.linear == 0.0


def test_small_errors_inside_the_deadband_are_ignored() -> None:
    tuning = FollowTuning(target_height=0.5, deadband=0.1)
    almost = person(0.26, 0.26, 0.74, 0.74)  # centre 0.5, height 0.48

    command = compute_command(almost, tuning)

    assert command.linear == 0.0
    assert command.angular == 0.0


def test_output_is_bounded_by_the_tuning_limits() -> None:
    tuning = FollowTuning(target_height=0.9, max_linear=0.4, max_angular=0.6)
    far_edge = person(0.99, 0.99, 1.0, 1.0)

    command = compute_command(far_edge, tuning)

    assert 0.0 <= command.linear <= tuning.max_linear
    assert -tuning.max_angular <= command.angular <= tuning.max_angular


# --- service ------------------------------------------------------------------


class FakeRover:
    """Records what the behaviour asks the rover to do."""

    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.stops = 0

    async def move(self, linear: float, angular: float) -> None:
        self.moves.append((linear, angular))

    async def stop(self) -> None:
        self.stops += 1


async def test_step_drives_the_rover_toward_the_target() -> None:
    rover = FakeRover()
    service = FollowService(
        rover, lambda: snapshot(person(0.7, 0.25, 0.95, 0.75)), tuning=FollowTuning()
    )

    await service.step()

    assert rover.moves, "the service must have issued a command"
    linear, angular = rover.moves[-1]
    assert angular < 0  # target on the right -> turn right
    assert service.status.has_target is True


async def test_step_stops_the_rover_when_there_is_no_target() -> None:
    rover = FakeRover()
    service = FollowService(rover, lambda: snapshot(), tuning=FollowTuning(lost_timeout=10))

    await service.step()

    assert rover.stops >= 1
    assert service.status.has_target is False


async def test_following_disables_itself_after_losing_the_target() -> None:
    rover = FakeRover()
    service = FollowService(rover, lambda: snapshot(), tuning=FollowTuning(lost_timeout=0.0))
    service._enabled = True  # start the behaviour without spawning its loop

    await service.step()

    assert service.enabled is False
    assert rover.stops >= 1


async def test_disable_always_stops_the_rover() -> None:
    rover = FakeRover()
    service = FollowService(rover, lambda: snapshot())

    await service.disable()

    assert rover.stops >= 1
    assert service.enabled is False
