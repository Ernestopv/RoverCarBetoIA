"""Safety layer.

Motion is critical: this layer is the single place where motion commands are
validated and clamped. No implementation may receive an unbounded command.
"""

from __future__ import annotations

import logging
import math

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import InvalidMotionCommandError
from app.rover.models import MotionCommand

logger = logging.getLogger(__name__)


class SafetyLimits(BaseModel):
    """Hard limits applied to every motion command."""

    model_config = ConfigDict(frozen=True)

    max_linear: float = Field(gt=0)
    max_angular: float = Field(gt=0)


class SafetyLayer:
    """Validates and clamps motion commands against the configured limits."""

    def __init__(self, limits: SafetyLimits) -> None:
        self._limits = limits

    @property
    def limits(self) -> SafetyLimits:
        return self._limits

    def validate(self, linear: float, angular: float) -> MotionCommand:
        """Return a safe command.

        Non-finite values are rejected outright: they almost always indicate a
        calculation bug upstream. Finite values outside the limits are clamped
        and logged, so a bad client cannot command an unsafe speed.
        """
        if not math.isfinite(linear) or not math.isfinite(angular):
            raise InvalidMotionCommandError(
                f"Motion command must be finite, got linear={linear!r} angular={angular!r}"
            )

        clamped = MotionCommand(
            linear=self._clamp(linear, self._limits.max_linear),
            angular=self._clamp(angular, self._limits.max_angular),
        )

        if clamped.linear != linear or clamped.angular != angular:
            logger.warning(
                "Motion command clamped: requested=(%.3f, %.3f) applied=(%.3f, %.3f)",
                linear,
                angular,
                clamped.linear,
                clamped.angular,
            )

        return clamped

    @staticmethod
    def _clamp(value: float, limit: float) -> float:
        return max(-limit, min(limit, value))
