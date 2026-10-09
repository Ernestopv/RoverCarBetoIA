"""Autonomous behaviour endpoints (Phase 7).

Enabling following is an operator action; the behaviour itself never moves the
rover on its own. Every command it issues goes through the rover service, so the
safety layer and the watchdog still apply.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.ai.follow import FollowService, FollowStatus
from app.api.dependencies import get_follow_service, get_rover_service
from app.rover.models import ConnectionState
from app.rover.service import RoverService

router = APIRouter(prefix="/behavior", tags=["behavior"])


class FollowRequest(BaseModel):
    """Enable or disable person following."""

    enabled: bool


@router.get("/status", response_model=FollowStatus, summary="Follow behaviour status")
async def status(service: FollowService = Depends(get_follow_service)) -> FollowStatus:
    """Whether following is enabled, and what it is doing right now."""
    return service.status


@router.post("/follow", response_model=FollowStatus, summary="Enable or disable following")
async def set_follow(
    payload: FollowRequest,
    service: FollowService = Depends(get_follow_service),
    rover: RoverService = Depends(get_rover_service),
) -> FollowStatus:
    """Turn person following on or off.

    Disabling (or turning it off) **always stops the rover**. Enabling is refused
    when the rover is not connected: following must never start blind.
    """
    if payload.enabled:
        current = await rover.status()
        if current.connection != ConnectionState.CONNECTED:
            raise HTTPException(
                status_code=409,
                detail="The rover is not connected; following was not enabled",
            )
        await service.enable()
    else:
        await service.disable(reason="operator")
    return service.status
