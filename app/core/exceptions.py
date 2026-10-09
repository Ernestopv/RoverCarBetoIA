"""Domain exceptions for RoverCarBeto.

Every exception carries enough context to be diagnosed from the logs. Avoid
generic exceptions when a specific one describes the failure.
"""

from __future__ import annotations


class RoverCarBetoError(Exception):
    """Base class for every application error."""


class ConfigurationError(RoverCarBetoError):
    """The configuration is invalid or an implementation is not available."""


class CameraError(RoverCarBetoError):
    """Base class for camera and video-stream errors."""


class CameraStreamError(CameraError):
    """The video stream could not be published or reached."""


class RoverError(RoverCarBetoError):
    """Base class for rover-related errors."""


class RoverConnectionError(RoverError):
    """The rover is not reachable or the link was lost."""


class RoverTimeoutError(RoverError):
    """The rover did not answer within the configured timeout."""


class RoverProtocolError(RoverError):
    """The rover answered with an unexpected or malformed response."""


class SafetyViolationError(RoverCarBetoError):
    """A command was rejected because it violates a safety rule."""


class InvalidMotionCommandError(SafetyViolationError):
    """A motion command contains invalid (non-finite) values."""
