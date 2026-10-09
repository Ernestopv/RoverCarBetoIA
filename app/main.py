"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.ai.broadcast import ResultBroadcaster
from app.ai.detection import DetectionService, InferenceSource
from app.ai.follow import FollowService, FollowTuning
from app.ai.pose import PoseService, PoseSource
from app.api.routes import ai as ai_routes
from app.api.routes import behavior, health, rover, telemetry
from app.api.routes import camera as camera_routes
from app.camera.factory import create_camera
from app.camera.health import rtsp_describe_ok, supervise_stream
from app.camera.imx500 import Imx500Camera
from app.camera.stream import publish_url
from app.core.config import Settings, get_settings
from app.core.exceptions import CameraError, RoverError, SafetyViolationError
from app.core.logging import configure_logging
from app.rover.factory import create_rover, create_safety_layer
from app.rover.service import RoverService
from app.telemetry.service import TelemetryService

logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    rover_service = RoverService(
        create_rover(settings),
        create_safety_layer(settings),
        command_timeout=settings.command_timeout,
        watchdog_interval=settings.watchdog_interval,
    )
    broadcaster = ResultBroadcaster()
    camera = create_camera(settings, on_result=broadcaster.notify)
    # The sensor holds one network at a time, so only one of the two services will
    # have anything to report. Both are wired: whichever matches the loaded
    # network answers, and the other says it is unavailable.
    model_name = (
        settings.camera_network_file.rsplit("/", 1)[-1]
        if settings.camera_mode == "imx500"
        else None
    )
    detection_service = DetectionService(
        camera if isinstance(camera, InferenceSource) else None,
        score_threshold=settings.ai_score_threshold,
        model=model_name,
    )
    pose_service = PoseService(
        camera if isinstance(camera, PoseSource) else None,
        person_threshold=settings.ai_pose_threshold,
        model=model_name,
    )
    telemetry_service = TelemetryService(rover_service.rover, detection_service)
    follow_service = FollowService(
        rover_service,
        detection_service.snapshot,
        tuning=FollowTuning(
            target_label=settings.follow_target_label,
            min_confidence=settings.follow_min_confidence,
            target_height=settings.follow_target_height,
            max_linear=settings.follow_max_linear,
            max_angular=settings.follow_max_angular,
            min_linear=settings.follow_min_linear,
            deadband=settings.follow_deadband,
            face_deadband=settings.follow_face_deadband,
            lost_timeout=settings.follow_lost_timeout,
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The camera notifies from its own thread, so it needs to know which loop
        # to deliver on. Bound here, before it starts producing.
        broadcaster.bind(asyncio.get_running_loop())

        try:
            await rover_service.start()
        except RoverError:
            # Do not prevent the API from serving status/telemetry.
            logger.exception("Initial rover connection failed; serving in disconnected state")

        if settings.camera_autostart:
            try:
                await camera.start()
            except CameraError:
                # A camera problem must never block manual control.
                logger.exception("Camera stream unavailable; driving still works")

        if settings.follow_auto_enable:
            try:
                await follow_service.enable()
            except Exception:  # noqa: BLE001 - never block startup on the behaviour
                logger.exception("Could not enable following at startup")

        watchdog_task: asyncio.Task[None] | None = None
        if settings.camera_autostart and isinstance(camera, Imx500Camera):
            rtsp_url = publish_url(
                settings.mediamtx_host,
                settings.mediamtx_rtsp_port,
                settings.camera_stream_path,
            )

            async def restart_publisher() -> None:
                # Only when the camera is supposed to be running: a model reload
                # owns its own stop/start. And wait for the publish, so the
                # watchdog does not restart again over the sensor's startup gap.
                if camera.is_running and not camera.is_reloading:
                    await camera.reload(camera.network_file, wait_for_publish=True)

            watchdog_task = asyncio.create_task(
                supervise_stream(
                    probe=lambda: rtsp_describe_ok(rtsp_url),
                    restart=restart_publisher,
                    # Never fight a deliberate camera restart: a model switch is
                    # in progress while the camera is not running *or* marked as
                    # reloading.
                    active=lambda: camera.is_running and not camera.is_reloading,
                ),
                name="stream-watchdog",
            )

        try:
            yield
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass
            await follow_service.disable(reason="shutdown")
            await camera.stop()
            await rover_service.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.rover_service = rover_service
    app.state.telemetry_service = telemetry_service
    app.state.camera = camera
    app.state.detection_service = detection_service
    app.state.pose_service = pose_service
    app.state.follow_service = follow_service
    app.state.result_broadcaster = broadcaster

    _register_exception_handlers(app)

    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(rover.router, prefix=API_V1_PREFIX)
    app.include_router(telemetry.router, prefix=API_V1_PREFIX)
    app.include_router(camera_routes.router, prefix=API_V1_PREFIX)
    app.include_router(ai_routes.router, prefix=API_V1_PREFIX)
    app.include_router(behavior.router, prefix=API_V1_PREFIX)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SafetyViolationError)
    async def _safety_violation_handler(
        _request: Request, exc: SafetyViolationError
    ) -> JSONResponse:
        logger.warning("Rejected unsafe command: %s", exc)
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(RoverError)
    async def _rover_error_handler(_request: Request, exc: RoverError) -> JSONResponse:
        logger.warning("Rover operation failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(CameraError)
    async def _camera_error_handler(_request: Request, exc: CameraError) -> JSONResponse:
        logger.warning("Camera operation failed: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # The default handler embeds the raw input in the response, which cannot
        # be serialized when it is NaN/Infinity. Sanitize it to keep a clean 422.
        detail = _json_safe(jsonable_encoder(exc.errors()))
        return JSONResponse(status_code=422, content={"detail": detail})


def _json_safe(value: Any) -> Any:
    """Replace non-JSON-compliant floats so the error response can be sent."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


app = create_app()
