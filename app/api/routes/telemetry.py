"""Telemetry endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_telemetry_service
from app.telemetry.service import TelemetryService, TelemetrySnapshot

router = APIRouter(tags=["telemetry"])


@router.get("/telemetry", response_model=TelemetrySnapshot, summary="Telemetry snapshot")
async def telemetry(
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetrySnapshot:
    return await service.snapshot()
