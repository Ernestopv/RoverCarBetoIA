"""Health endpoint schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Basic liveness information about the service."""

    status: Literal["ok"] = "ok"
    app: str
    version: str
    environment: str
    rover_mode: str
    camera_mode: str
