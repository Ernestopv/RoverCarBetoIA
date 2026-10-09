"""Application configuration.

All configuration is read from environment variables (and an optional `.env`
file). Nothing in the application may hard-code hosts, ports, credentials or
safety limits: they must come from here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RoverMode = Literal["simulator", "hardware"]
CameraMode = Literal["simulator", "imx500"]

#: Default discharge curve for the 3S Li-ion pack, as (voltage V, percent) pairs.
#: A straight line between min and max is a poor model for Li-ion: the voltage is
#: almost flat between 3.9-4.0 V per cell and falls steeply near the end, so the
#: linear map both over-honours the plateau and hides a nearly dead pack.
DEFAULT_BATTERY_CURVE: tuple[tuple[float, float], ...] = (
    (12.60, 100.0),
    (12.15, 85.0),
    (11.91, 70.0),
    (11.67, 55.0),
    (11.40, 40.0),
    (11.10, 25.0),
    (10.80, 12.0),
    (10.50, 5.0),
    (10.20, 2.0),
    (9.90, 0.0),
)


class Settings(BaseSettings):
    """Runtime settings for RoverCarBeto."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General -------------------------------------------------------------
    app_name: str = "RoverCarBeto"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # --- API -----------------------------------------------------------------
    api_host: str = "0.0.0.0"  # noqa: S104 - the API is served behind nginx/Docker
    api_port: int = Field(default=8000, ge=1, le=65535)

    # --- Modes ---------------------------------------------------------------
    # Defaults keep the project runnable without any physical hardware.
    rover_mode: RoverMode = "simulator"

    # --- Camera --------------------------------------------------------------
    camera_mode: CameraMode = "simulator"
    camera_width: int = Field(default=1280, ge=160, le=3840)
    camera_height: int = Field(default=720, ge=120, le=2160)
    camera_fps: int = Field(default=30, ge=1, le=120)
    camera_bitrate_kbps: int = Field(default=2500, ge=100, le=50_000)
    camera_stream_path: str = "rover"
    camera_autostart: bool = True
    # Neural network uploaded to the IMX500 sensor (used by CAMERA_MODE=imx500).
    #
    # SSD-MobileNetV2-FPNLite was chosen over the more obvious
    # efficientdet_lite0. Both are post-processed on the sensor, but
    # efficientdet declares `preserve_aspect_ratio`, so its square input does not
    # cover the video frame and every box comes out offset. SSD-MobileNet returns
    # boxes already normalised to 0..1, which map straight onto the picture.
    camera_network_file: str = (
        "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
    )
    camera_buffer_count: int = Field(default=3, ge=2, le=32)
    # Mirror the stream when the camera is mounted upside down or backwards.
    # A 180-degree rotation is `hflip` AND `vflip` together, which is how
    # libcamera models a transform.
    camera_hflip: bool = False
    camera_vflip: bool = False

    # --- AI (Phase 6) --------------------------------------------------------
    # Minimum confidence for the detector to report an object.
    ai_score_threshold: float = Field(default=0.5, ge=0, le=1)
    # Minimum confidence for the pose network to consider a person. Separate from
    # the detection threshold on purpose: the two networks do not score on the
    # same scale, and the official pose example uses 0.3 where detection uses
    # 0.55.
    ai_pose_threshold: float = Field(default=0.3, ge=0, le=1)

    # --- Behaviour: person following (Phase 7) -------------------------------
    # Off by default: no autonomous motion happens until an operator enables it
    # (or FOLLOW_AUTO_ENABLE brings it up at startup). Commands still pass through
    # the safety layer, and the rover never reverses while following.
    follow_auto_enable: bool = False
    follow_target_label: str = "person"
    follow_min_confidence: float = Field(default=0.5, ge=0, le=1)
    # Approach until the person's bbox reaches this height (0..1): the minimum
    # distance. Bigger = it gets closer before it stops.
    follow_target_height: float = Field(default=0.7, gt=0, lt=1)
    follow_max_linear: float = Field(default=0.4, gt=0, le=1)
    follow_max_angular: float = Field(default=0.6, gt=0, le=1)
    # Smallest forward speed, so static friction does not stall the approach.
    follow_min_linear: float = Field(default=0.15, ge=0, le=1)
    follow_deadband: float = Field(default=0.06, ge=0, lt=0.5)
    # Only drive forward when the person is within this horizontal distance of the
    # centre; otherwise it turns in place.
    follow_face_deadband: float = Field(default=0.2, ge=0, le=0.5)
    follow_lost_timeout: float = Field(default=10.0, gt=0)

    # --- MediaMTX ------------------------------------------------------------
    # Host of the MediaMTX server *as seen by the backend* (the compose service
    # name when running in containers).
    mediamtx_host: str = "localhost"
    mediamtx_rtsp_port: int = Field(default=8554, ge=1, le=65535)
    # Port the *browser* uses for WebRTC/WHEP.
    mediamtx_webrtc_port: int = Field(default=8889, ge=1, le=65535)

    # --- Safety limits -------------------------------------------------------
    max_linear_speed: float = Field(default=1.0, gt=0, le=10)
    max_angular_speed: float = Field(default=1.5, gt=0, le=10)
    command_timeout: float = Field(
        default=0.5,
        gt=0,
        description="Seconds without a command before the watchdog stops the rover.",
    )
    watchdog_interval: float = Field(default=0.1, gt=0)

    # --- WAVE ROVER Wi-Fi connection (Phase 4) -------------------------------
    wave_rover_host: str = "192.168.1.100"
    wave_rover_port: int = Field(default=80, ge=1, le=65535)
    wave_rover_timeout: float = Field(default=1.0, gt=0)
    # Transport: "wifi" (default, HTTP over the chassis AP) or "serial" (header
    # UART at 115200). Serial is opt-in until it is benched and trusted.
    wave_rover_transport: Literal["wifi", "serial"] = "wifi"
    wave_rover_serial_port: str = "/dev/ttyAMA0"
    # The chassis protocol (CMD_SPEED_CTRL) takes wheel speeds in +-0.5, where
    # 0.5 means 100% PWM. Internal commands are normalised to +-1, so 1.0 maps
    # to this value.
    wave_rover_max_speed: float = Field(default=0.5, gt=0, le=0.5)
    # 3S pack discharge curve (voltage V, percent). The chassis reports volts, so
    # this is how a charge level is estimated; see DEFAULT_BATTERY_CURVE.
    wave_rover_battery_curve: list[tuple[float, float]] = Field(
        default_factory=lambda: list(DEFAULT_BATTERY_CURVE)
    )
    # Chassis speed rate (CMD_SET_SPD_RATE), applied on connect only when the
    # chassis has it at zero: this unit's boot.mission resets it to 0 on every
    # power-up, and with a rate of 0 no motion command has any effect.
    wave_rover_speed_rate: float = Field(default=1.0, gt=0, le=1.0)
    # Per-wheel gain (1.0 = no correction). Real motors differ slightly, so a
    # chassis that veers while commanded straight is trimmed here rather than in
    # the mixing maths. Tune it on the bench: drive straight and adjust.
    wave_rover_left_trim: float = Field(default=1.0, gt=0, le=2.0)
    wave_rover_right_trim: float = Field(default=1.0, gt=0, le=2.0)

    # --- Simulator -----------------------------------------------------------
    simulator_latency: float = Field(default=0.0, ge=0)
    simulator_failure_rate: float = Field(default=0.0, ge=0, le=1)

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def is_simulator(self) -> bool:
        """True when the rover runs against the simulator."""
        return self.rover_mode == "simulator"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
