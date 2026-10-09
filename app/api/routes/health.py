"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_settings
from app.api.schemas.health import HealthResponse
from app.core.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness probe: always answers, even when the rover is disconnected."""
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        rover_mode=settings.rover_mode,
        camera_mode=settings.camera_mode,
    )
