"""The networks the operator may choose from.

The sensor holds **one network at a time**, and the loaded one is decided before
the camera starts. This is the whitelist of what the application knows how to
interpret and what the interface may switch to: a raw ``CAMERA_NETWORK_FILE`` can
point at any ``.rpk``, but the ones listed here are the only ones with a decoder
on our side.

The throughput figures are the **measured** ones (see ``docs/specs/imx500.md``),
not the nominal ones the model declares, because that is what the operator will
actually notice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    """One switchable network."""

    id: str
    task: str
    file: str
    description: str

    @property
    def file_name(self) -> str:
        return self.file.rsplit("/", 1)[-1]


AVAILABLE_MODELS: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="detection",
        task="object detection",
        file="/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk",
        description=(
            "Bounding boxes and labels for 80 COCO classes (person, car, chair...). "
            "Measured ~8.5 updates per second."
        ),
    ),
    ModelProfile(
        id="pose",
        task="pose estimation",
        file="/usr/share/imx500-models/imx500_network_higherhrnet_coco.rpk",
        description=(
            "The 17 joints of up to 30 people, drawn as skeletons. Measured ~3 updates per second."
        ),
    ),
)


def profile_by_id(model_id: str) -> ModelProfile | None:
    return next((profile for profile in AVAILABLE_MODELS if profile.id == model_id), None)


def profile_for_file(file_name: str | None) -> ModelProfile | None:
    """The profile whose file is loaded, given the file name reported by the camera.

    The camera reports only the base name; the whitelist holds full paths, so they
    are compared on the base name.
    """
    if not file_name:
        return None
    return next(
        (profile for profile in AVAILABLE_MODELS if profile.file_name == file_name),
        None,
    )
