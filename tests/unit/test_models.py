"""Tests for the model whitelist.

This list is the safety boundary of the model switch: only these networks appear
in the interface, so an operator cannot ask for an arbitrary ``.rpk``.
"""

from __future__ import annotations

from app.ai.models import AVAILABLE_MODELS, profile_by_id, profile_for_file


def test_the_whitelist_holds_detection_and_pose() -> None:
    ids = {profile.id for profile in AVAILABLE_MODELS}

    assert ids == {"detection", "pose"}


def test_the_whitelist_declares_a_supported_task_per_model() -> None:
    by_id = {profile.id: profile for profile in AVAILABLE_MODELS}

    assert by_id["detection"].task == "object detection"
    assert by_id["pose"].task == "pose estimation"


def test_profile_by_id_is_exact() -> None:
    assert profile_by_id("detection") is not None
    assert profile_by_id("pose") is not None
    assert profile_by_id("no-such-model") is None


def test_profile_for_file_matches_the_base_name() -> None:
    """The camera reports only the file name; the whitelist holds full paths."""
    assert profile_for_file("imx500_network_higherhrnet_coco.rpk") is not None
    assert profile_for_file("imx500_network_higherhrnet_coco.rpk").id == "pose"  # type: ignore[union-attr]
    assert profile_for_file(None) is None
    assert profile_for_file("some_other_network.rpk") is None
