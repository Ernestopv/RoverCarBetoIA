"""Camera factory.

Selects the camera implementation from configuration:

- ``simulator`` (default): a synthetic FFmpeg signal. Runs anywhere.
- ``imx500``: the Raspberry Pi AI Camera. Only runs on the Pi, and says so
  clearly if it is asked to start elsewhere.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.camera.imx500 import Imx500Camera
from app.camera.interface import Camera
from app.camera.simulator import SimulatedCamera
from app.camera.stream import publish_url
from app.core.config import Settings
from app.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def create_camera(settings: Settings, *, on_result: Callable[[], None] | None = None) -> Camera:
    """Build the camera implementation selected by the configuration.

    ``on_result`` is called, from the camera's own thread, every time a new
    inference result is ready. It is how the interface is told there is something
    new instead of asking repeatedly.
    """
    publish = publish_url(
        settings.mediamtx_host,
        settings.mediamtx_rtsp_port,
        settings.camera_stream_path,
    )
    common = {
        "rtsp_url": publish,
        "stream_path": settings.camera_stream_path,
        "webrtc_port": settings.mediamtx_webrtc_port,
        "width": settings.camera_width,
        "height": settings.camera_height,
        "fps": settings.camera_fps,
    }

    if settings.camera_mode == "simulator":
        logger.info(
            "Camera mode: simulator (%dx%d @ %dfps, path '%s')",
            settings.camera_width,
            settings.camera_height,
            settings.camera_fps,
            settings.camera_stream_path,
        )
        return SimulatedCamera(bitrate_kbps=settings.camera_bitrate_kbps, **common)

    if settings.camera_mode == "imx500":
        logger.info(
            "Camera mode: imx500 (network '%s', path '%s')",
            settings.camera_network_file,
            settings.camera_stream_path,
        )
        return Imx500Camera(
            network_file=settings.camera_network_file,
            bitrate_kbps=settings.camera_bitrate_kbps,
            buffer_count=settings.camera_buffer_count,
            hflip=settings.camera_hflip,
            vflip=settings.camera_vflip,
            score_threshold=settings.ai_score_threshold,
            pose_threshold=settings.ai_pose_threshold,
            on_result=on_result,
            **common,
        )

    raise ConfigurationError(f"Unsupported CAMERA_MODE: {settings.camera_mode!r}")
