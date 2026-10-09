"""Rover motion endpoints.

Every endpoint goes through the service layer, never to a low-level motor call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_rover_service
from app.api.schemas.rover import MotionRequest
from app.rover.models import RoverStatus
from app.rover.service import RoverService

router = APIRouter(prefix="/rover", tags=["rover"])


@router.get("/status", response_model=RoverStatus, summary="Current rover status")
async def status(service: RoverService = Depends(get_rover_service)) -> RoverStatus:
    return await service.status()


@router.post("/move", response_model=RoverStatus, summary="Apply a motion command")
async def move(
    payload: MotionRequest,
    service: RoverService = Depends(get_rover_service),
) -> RoverStatus:
    """Move the rover.

    The command is validated, clamped by the safety layer and armed with the
    watchdog, so it automatically stops if no further command arrives.
    """
    return await service.move(linear=payload.linear, angular=payload.angular)


@router.post("/stop", response_model=RoverStatus, summary="Stop the rover now")
async def stop(service: RoverService = Depends(get_rover_service)) -> RoverStatus:
    """STOP takes priority over any other command and never fails the caller."""
    return await service.stop()
