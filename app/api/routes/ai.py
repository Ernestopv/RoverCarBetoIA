"""AI endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.datastructures import State

from app.ai.broadcast import ResultBroadcaster
from app.ai.detection import DetectionService, DetectionSnapshot
from app.ai.models import AVAILABLE_MODELS, profile_by_id, profile_for_file
from app.ai.pose import PoseService, PoseSnapshot
from app.api.dependencies import (
    get_camera,
    get_detection_service,
    get_pose_service,
    get_rover_service,
)
from app.camera.imx500 import Imx500Camera
from app.camera.interface import Camera
from app.core.exceptions import CameraError
from app.rover.service import RoverService

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/detections", response_model=DetectionSnapshot, summary="Latest detections")
async def detections(
    service: DetectionService = Depends(get_detection_service),
) -> DetectionSnapshot:
    """Objects seen by the sensor's network, in normalised frame coordinates.

    Nothing is recorded: the snapshot describes the latest inference result and
    is replaced by the next one.

    Reports ``available: false`` when the loaded network is not an object
    detector, which is the case while a pose network is loaded.
    """
    return service.snapshot()


@router.get("/pose", response_model=PoseSnapshot, summary="Latest pose estimation")
async def pose(
    service: PoseService = Depends(get_pose_service),
) -> PoseSnapshot:
    """People and their joints, in normalised frame coordinates.

    The sensor holds **one network at a time**, so this only has anything to say
    while a pose network is loaded; otherwise it reports ``available: false``.
    The snapshot carries the joint names and the skeleton, so the interface does
    not have to hard-code them.

    Nothing is recorded: the snapshot describes the latest result and is replaced
    by the next one.
    """
    return service.snapshot()


# --- choosing which network the sensor runs -----------------------------------


class ModelDescription(BaseModel):
    id: str
    task: str
    description: str


class ModelsReport(BaseModel):
    """Which networks exist and which one is loaded right now."""

    active: str | None = None
    models: list[ModelDescription] = Field(default_factory=list)


class ModelSwitchRequest(BaseModel):
    id: str


# Serialises switches: two concurrent requests must not tear the camera apart.
_MODEL_SWITCH_LOCK = asyncio.Lock()


def _report(models: list[ModelDescription], active: str | None) -> ModelsReport:
    return ModelsReport(active=active, models=models)


@router.get("/models", response_model=ModelsReport, summary="Networks the sensor can run")
async def models(camera: Camera = Depends(get_camera)) -> ModelsReport:
    """The whitelist of switchable networks and which one is loaded.

    Only the models this application knows how to interpret appear here; a raw
    ``CAMERA_NETWORK_FILE`` can point at any ``.rpk``, but switching is limited to
    what the interface can actually use.
    """
    status = await camera.status()
    active_profile = profile_for_file(status.model)
    models_list = [
        ModelDescription(id=profile.id, task=profile.task, description=profile.description)
        for profile in AVAILABLE_MODELS
    ]
    return _report(models_list, active_profile.id if active_profile else None)


@router.post("/model", response_model=ModelsReport, summary="Load a different network")
async def switch_model(
    change: ModelSwitchRequest,
    camera: Camera = Depends(get_camera),
    rover: RoverService = Depends(get_rover_service),
    detection: DetectionService = Depends(get_detection_service),
    pose: PoseService = Depends(get_pose_service),
) -> ModelsReport:
    """Load another network into the sensor.

    The sensor holds one network at a time, so this **restarts the camera**: the
    video drops and the inference of the old model stops. The first load of a
    network uploads firmware to the sensor and takes tens of seconds.

    Refused while the rover is moving: switching models leaves the operator blind
    for a moment, so it must not happen on a moving rover.
    """
    profile = profile_by_id(change.id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown model {change.id!r}; see GET /ai/models",
        )

    # Safety before everything: switching leaves the operator blind for a moment,
    # so it must never happen on a moving rover, whatever the camera is.
    rover_status = await rover.status()
    if rover_status.linear != 0.0 or rover_status.angular != 0.0:
        raise HTTPException(
            status_code=409,
            detail="The rover is moving; stop it before switching models",
        )

    if not isinstance(camera, Imx500Camera):
        raise HTTPException(
            status_code=400,
            detail="Model switching needs the IMX500 camera; it is running in simulator mode",
        )

    if _MODEL_SWITCH_LOCK.locked():
        raise HTTPException(status_code=409, detail="A model switch is already in progress")

    async with _MODEL_SWITCH_LOCK:
        try:
            # The request only answers when the stream is being published
            # again, so the interface's "loading" window covers the whole
            # restart instead of vanishing mid-reload.
            await camera.reload(profile.file, wait_for_publish=True)
        except CameraError as exc:
            # `reload` restores the previous network, so the camera is still
            # usable - the switch is what failed.
            raise HTTPException(
                status_code=502, detail=f"Could not load the network: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - the detail is what the operator sees
            raise HTTPException(status_code=502, detail=f"Switch failed: {exc}") from exc

        model_name = profile.file_name
        detection.set_model(model_name)
        pose.set_model(model_name)

    models_list = [
        ModelDescription(id=profile.id, task=profile.task, description=profile.description)
        for profile in AVAILABLE_MODELS
    ]
    return _report(models_list, profile.id)


# --- the live stream ----------------------------------------------------------


def _message(state: State) -> dict[str, Any]:
    """Both snapshots, ready to send.

    The one that does not match the loaded network answers ``available: false``
    almost for free, and sending both keeps the interface from having to know
    which network is loaded.
    """
    detection: DetectionService = state.detection_service
    pose: PoseService = state.pose_service
    return {
        "detections": detection.snapshot().model_dump(mode="json"),
        "pose": pose.snapshot().model_dump(mode="json"),
    }


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    """Push every inference result as the sensor produces it.

    Polling made the interface sample *slower than the sensor*: the pose network
    infers ten times a second and it was being asked four, so most results never
    reached the screen. Here the socket is woken up the moment a result lands, so
    nothing is thrown away and there is no per-request overhead.

    Subscribers are only told that there is something new; each one then reads the
    snapshot, so a slow browser cannot hold up the inference or the other clients.
    """
    await websocket.accept()

    state = websocket.app.state
    broadcaster: ResultBroadcaster = state.result_broadcaster
    listener = broadcaster.subscribe()

    try:
        # Something to look at straight away, before the first result arrives.
        await websocket.send_json(_message(state))

        while True:
            await listener.wait()
            listener.clear()
            await websocket.send_json(_message(state))
    except WebSocketDisconnect:
        # The browser navigated away or the network dropped: normal, not an error.
        pass
    finally:
        broadcaster.unsubscribe(listener)
