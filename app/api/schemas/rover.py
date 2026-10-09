"""Rover endpoint schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MotionRequest(BaseModel):
    """Body of ``POST /api/v1/rover/move``.

    ``linear`` and ``angular`` are normalized: ``-1`` is full reverse/right,
    ``+1`` is full forward/left, ``0`` means no motion on that axis. Values
    beyond the configured limits are clamped by the safety layer; non-finite
    values are rejected with ``422``.
    """

    model_config = ConfigDict(extra="forbid")

    linear: float = Field(default=0.0, allow_inf_nan=False)
    angular: float = Field(default=0.0, allow_inf_nan=False)
