"""FastAPI dependencies.

The service instances live in ``app.state`` and are injected into the routes,
so endpoints never build their own hardware objects.
"""

from __future__ import annotations

from fastapi import Request

from app.ai.detection import DetectionService
from app.ai.follow import FollowService
from app.ai.pose import PoseService
from app.camera.interface import Camera
from app.core.config import Settings
from app.rover.service import RoverService
from app.telemetry.service import TelemetryService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rover_service(request: Request) -> RoverService:
    return request.app.state.rover_service


def get_telemetry_service(request: Request) -> TelemetryService:
    return request.app.state.telemetry_service


def get_camera(request: Request) -> Camera:
    return request.app.state.camera


def get_detection_service(request: Request) -> DetectionService:
    return request.app.state.detection_service


def get_pose_service(request: Request) -> PoseService:
    return request.app.state.pose_service


def get_follow_service(request: Request) -> FollowService:
    return request.app.state.follow_service
