"""Camera endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_camera
from app.camera.interface import Camera, CameraStatus

router = APIRouter(prefix="/camera", tags=["camera"])


@router.get("/status", response_model=CameraStatus, summary="Camera stream status")
async def camera_status(camera: Camera = Depends(get_camera)) -> CameraStatus:
    """Whether the live stream is publishing, and how the browser reaches it."""
    return await camera.status()
